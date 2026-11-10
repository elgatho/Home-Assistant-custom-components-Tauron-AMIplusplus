"""Account balance ("Saldo") from the Mój TAURON invoices page (https://moj.tauron.pl/.../faktury)."""
import html
import json
import re
from dataclasses import dataclass, field
from typing import Optional

VIEW_MODEL_MARKER = "var serializedViewModel ="


@dataclass
class SupplyPointBalance:
    name: str
    energy_type: Optional[str]
    address: Optional[str]
    point_number: Optional[str]
    balance: float
    overdue: Optional[float] = None
    current: Optional[float] = None
    interest: Optional[float] = None


@dataclass
class AccountBalance:
    total: float
    points: list[SupplyPointBalance] = field(default_factory=list)


def parse_amount(text: str) -> Optional[float]:
    """'1 048,04 zł' -> 1048.04"""
    match = re.search(r"-?\d[\d\s ]*(?:,\d+)?", text or "")
    if match is None:
        return None
    return float(re.sub(r"[\s ]", "", match.group()).replace(",", "."))


def extract_view_model(page_html: str) -> dict:
    """The page embeds `var serializedViewModel = {...};` which the browser echoes back as `parentViewModel`."""
    start = page_html.find(VIEW_MODEL_MARKER)
    if start < 0:
        raise ValueError("serializedViewModel not found")
    start = page_html.index("{", start)
    model, _ = json.JSONDecoder().raw_decode(page_html, start)
    return model


def flatten_view_model(model: dict, prefix: str = "parentViewModel") -> dict[str, str]:
    """{'A': {'B': 'x'}} -> {'parentViewModel[A][B]': 'x'} (jQuery $.param style, None -> '')."""
    out: dict[str, str] = {}
    for key, value in model.items():
        name = f"{prefix}[{key}]"
        if isinstance(value, dict):
            out.update(flatten_view_model(value, name))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out.update(flatten_view_model(item, f"{name}[{i}]"))
                else:
                    out[f"{name}[{i}]"] = "" if item is None else str(item)
        elif value is None:
            out[name] = ""
        elif isinstance(value, bool):
            out[name] = "true" if value else "false"
        else:
            out[name] = str(value)
    return out


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def _first(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, re.S)
    return match.group(1) if match else None


def _details(block: str) -> dict[str, Optional[float]]:
    """Amounts of the 'Przeterminowane' / 'Bieżące' / 'Razem' sections ('Łącznie' row, 'Nota odsetkowa' row)."""
    result: dict[str, Optional[float]] = {}
    for title, body in re.findall(r'<div class="subheader">(.*?)</div>\s*<dl[^>]*>(.*?)</dl>', block, re.S):
        rows = dict(re.findall(r"<dt>(.*?)</dt>\s*<dd>(.*?)</dd>", body, re.S))
        rows = {_text(k): parse_amount(_text(v)) for k, v in rows.items()}
        result[_text(title)] = rows.get("Łącznie")
        result[f"{_text(title)}/interest"] = rows.get("Nota odsetkowa")
    return result


def parse_account_balance(result_html: str) -> AccountBalance:
    """Parse `ResultHtml` returned by /api/sitecore/EbokInvoiceList/LoadMoreInvoicesProducts."""
    blocks = re.split(r'(?=<div class="row\s+invoice-row">)', result_html)[1:]
    points: list[SupplyPointBalance] = []
    for block in blocks:
        amount_column = _first(r'(<div class="col-xs-12 col-sm-4 amount-column.*?)(?=<div class="row row-details-container">|$)', block)
        amount_text = _first(r'<div class="amount[^"]*">(.*?)</div>', amount_column or "")
        balance = parse_amount(_text(amount_text)) if amount_text else None
        if balance is None:
            continue
        # credit balance is shown with the "Nadpłata" label
        if "Nadpłata" in _text(amount_column or ""):
            balance = -abs(balance)
        details = _details(block)
        name = _first(r"<h3>(.*?)</h3>", block)
        address = _first(r'<div class="float-box">\s*<p>(.*?)</p>', block)
        points.append(SupplyPointBalance(
            name=_text(name) if name else "",
            energy_type=_text(_first(r"<span>(.*?)</span>", block) or "") or None,
            address=_text(re.sub(r",?\s*</br>", ", ", address)) if address else None,
            point_number=_first(r"Numer Punktu Poboru:\s*(\d+)", block),
            balance=balance,
            overdue=details.get("Przeterminowane"),
            current=details.get("Bieżące"),
            interest=details.get("Razem/interest"),
        ))
    return AccountBalance(total=round(sum(p.balance for p in points), 2), points=points)
