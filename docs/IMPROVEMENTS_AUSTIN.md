# Proposed improvements (fork of 54yyyu/zotero-mcp 0.17.2)

Purpose: resolve `[CHECK]` items in dissertation literature-review strands, which
means confirming that a quotation exists in the source and finding the page
number **as printed** (the page label), not the PDF's physical page index.

## What upstream already gives us

- `zotero_read_pdf_pages` reads pages by **physical** index (1-based), as text or images.
- `pdf_utils.get_page_label()` exists, and annotations carry `annotationPageLabel`.
- `zotero_get_item_fulltext` returns the synced full-text index, which has no page
  breaks, so it can confirm wording but never a locator.
- Works over the web API when the PDF is in Zotero cloud storage.

## Gap

No tool takes "this quote, this item" and answers "found on printed page 214
(PDF page 19), here is the surrounding text." Today the model must guess a page
range, read it, and compare by eye, and scanned chapters often have no embedded
page labels at all, so a physical index gets reported as a page number.

## Proposals, in priority order

1. **`zotero_verify_quote(item_key, quote, claimed_page=None)`** (new, read-only)
   - Fuzzy match across every page: normalise curly quotes, ligatures, soft
     hyphens and line-break hyphenation, whitespace, and ellipses inside the quote.
   - Return: match found / not found, confidence, physical page, embedded PDF page
     label, printed folio detected from the running header/footer, ~200 chars of
     context, and whether `claimed_page` agrees.
   - Report "cross-page" quotes as `pp. 214–215`.
2. **Printed-page inference.** When the PDF has no page labels (common for scanned
   book chapters), read the folio from header/footer text and compute a per-item
   offset; flag the result as inferred so it can still be marked `[CHECK]` if weak.
3. **`zotero_read_pdf_pages(..., page_label="214")`.** Let the model open a page by
   its printed number.
4. **`zotero_verify_quotes` batch tool.** Input: a list of `{item_key or citation, quote,
   claimed_page}` pulled from a draft. Output: a table of verified / page corrected /
   not found, ready to paste into an audit log.
5. **Server hardening.** Run with a read-only Zotero API key and only the read
   toolsets, so ChatGPT/Claude can never edit the library; add a `/healthz` route
   for the tunnel.
6. **Keep upstream in sync.** A GitHub Action that opens a PR when 54yyyu tags a
   new release, plus tests for the new tools using a small fixture PDF with
   roman-numeral front matter and offset page labels.

Items 1 to 3 cover the dissertation need. Nothing here changes the live server
until Austin approves a deploy.
