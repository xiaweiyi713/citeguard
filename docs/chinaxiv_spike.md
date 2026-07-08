# ChinaXiv Open-Endpoint Feasibility Spike

**Goal:** Determine whether ChinaXiv (中国科学院科技论文预发布平台) exposes a usable, open, machine-readable metadata endpoint that we could implement a `MetadataSource` adapter against, without scraping login- or subscription-gated content.

**Date:** 2026-06-04

## Method

We probed only documented/obvious open endpoints (OAI-PMH and a couple of plausible API/OAI path variants) with short timeouts and a descriptive User-Agent. We did **not** attempt to access any login-gated, paywalled, or restricted content. Each probe outcome is recorded verbatim below.

## Attempts

| # | URL | Method/UA | Result |
|---|-----|-----------|--------|
| 1 | `https://www.chinaxiv.org/oai/OAIHandler?verb=Identify` | GET, `CiteGuard/0.2 (mailto:research@example.com)` | HTTP **200** (nginx), but body is 43-byte plain text: `Sorry!You have no right to access this web.` No `Content-Type` header. **Not XML, access denied.** |
| 2 | `http://www.chinaxiv.org/oai/OAIHandler?verb=Identify` | GET, `CiteGuard/0.2` | HTTP **301 Moved Permanently** (redirect to HTTPS). |
| 3 | `https://www.chinaxiv.org/home.htm` | GET | HTTP **200** — public site home page is reachable (HTML). Not a metadata API. |
| 4 | `https://www.chinaxiv.org/oai/OAIHandler?verb=ListRecords&metadataPrefix=oai_dc` | GET | HTTP **200**, identical 43-byte body: `Sorry!You have no right to access this web.` **Access denied, no records returned.** |
| 5 | `https://www.chinaxiv.org/oai/OAIHandler?verb=Identify` | GET, `CiteGuard/0.2` (re-probe for headers) | HTTP **200**, same access-denied body, no `Content-Type`. Confirms the deny is consistent regardless of UA. |
| 6 | `https://www.chinaxiv.org/oai2?verb=Identify` | GET | HTTP **404 Not Found**. |
| 7 | `https://www.chinaxiv.org/oai?verb=Identify` | GET | HTTP **301** redirect (no usable OAI response). |
| 8 | `https://www.chinaxiv.org/api` | GET | HTTP **404 Not Found**. |

### Key observations

- The `/oai/OAIHandler` path *does* exist on the server (it answers `200` rather than `404`), so an OAI-PMH handler is plausibly deployed — but it is **gated**. Every OAI verb we tried (`Identify`, `ListRecords`) returns the same short access-denied text, not an OAI-PMH XML envelope (no `<OAI-PMH>` root, no `<Identify>`/`<ListRecords>` element, no `Content-Type: text/xml`).
- The denial is not an authentication challenge we are permitted to satisfy: there is no documented open token, and changing the User-Agent does not change the outcome. The most likely cause is IP-/network-level allowlisting (e.g. partner harvesters or domestic IP ranges) — i.e. the endpoint is **not open to the public**.
- No plausible alternate path (`/oai2`, `/api`) returned a structured metadata response.

## Finding

**NO-GO.**

ChinaXiv does not expose a confirmed, open, machine-readable metadata endpoint that we can harvest without restricted access. The one OAI-PMH-shaped path that exists (`/oai/OAIHandler`) responds to every verb with a 43-byte access-denied message and no OAI-PMH XML, indicating the endpoint is gated (most likely allowlist-restricted). We found no open JSON API surface. Implementing a reliable `MetadataSource` adapter would therefore require either credentialed/allowlisted access we do not have, or scraping gated content — which is explicitly out of scope.

## Decision

We will **not** integrate ChinaXiv as a metadata source at this time.

- CiteGuard retains its pluggable `MetadataSource` interface (`citeguard/retrieval/scholarly_clients/base.py`) and the `build_live_metadata_source` factory (`citeguard/retrieval/scholarly_clients/factory.py`). A `ChinaxivMetadataSource` adapter can be added later **without architectural changes** once an open, documented endpoint is confirmed.
- We will **not** scrape login-gated, paywalled, or otherwise restricted ChinaXiv content. A future revisit should re-probe `/oai/OAIHandler` for an open OAI-PMH response, or look for an officially documented open API / data-dump program.

### If this ever flips to GO (follow-up, not part of this task)

If an open endpoint is later confirmed:

1. Implement `ChinaxivMetadataSource` following the pattern of `citeguard/retrieval/scholarly_clients/crossref.py` and `citeguard/retrieval/scholarly_clients/openalex.py` (injected HTTP client, normalize results into the shared metadata record shape).
2. Add a unit test using a Fake HTTP client (no live network in tests), mirroring the existing client tests.
3. Register the source in `build_live_metadata_source` (`citeguard/retrieval/scholarly_clients/factory.py`) under a `chinaxiv` name.
