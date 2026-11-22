"""Federated read across registered plants (spec Part V, Federated Read).

Ask every selected plant in parallel, merge the answers, sort by timestamp,
and report every plant that didn't answer — so a missing plant reads as
*unknown*, never as *no history*. Each plant's own store stays
authoritative; nothing is replicated.

Transport is the host's: it passes a `fetch(site_id, site)` coroutine that
asks one plant (waterworks-ai calls each plant's audit history tool through
that plant's aggregator). Part V limits federated read to audit history —
never protocol adapters, write tools or memory stores — and that limit is
the host's to keep in what its fetch calls.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

S = TypeVar("S")


class UnknownSiteError(KeyError):
    """The request named a site_id that isn't registered."""

    def __init__(self, site_id: str, known: list[str]):
        self.site_id = site_id
        self.known = known
        listed = ", ".join(known) or "(none registered)"
        super().__init__(f"unknown site_id {site_id!r}. Known sites: {listed}.")

    def __str__(self) -> str:  # KeyError's default repr-quotes the message
        return str(self.args[0])


class SiteUnavailable(Exception):
    """Raised by a fetch to mark its plant as not answering, with a reason —
    e.g. the site has no aggregator_url, or the plant returned a malformed
    response. Any other exception is reported the same way."""


@dataclass
class FederatedResult(Generic[S]):
    records: list[dict[str, Any]] = field(default_factory=list)
    """Every plant's records, merged and sorted by timestamp ascending. Each
    keeps the site_id its plant stamped on it (stamped here if absent)."""

    queried: list[str] = field(default_factory=list)
    """Every site_id asked, in registry order."""

    unavailable: dict[str, str] = field(default_factory=dict)
    """site_id → reason, for every plant that failed, timed out or was
    skipped. Empty means every plant answered."""

    @property
    def complete(self) -> bool:
        return not self.unavailable

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "queried": self.queried,
            "unavailable": self.unavailable,
            "complete": self.complete,
        }


async def federated_read(
    sites: Mapping[str, S],
    fetch: Callable[[str, S], Awaitable[list[dict[str, Any]]]],
    *,
    site_id: str | None = None,
    timeout: float | None = None,
    sort_key: str = "ts",
) -> FederatedResult[S]:
    """Fan a read out to every selected plant and merge the answers.

    Args:
        sites: The registry, site_id → site (e.g. EnterpriseConfig.sites()).
        fetch: Coroutine asking one plant; returns that plant's records.
        site_id: Restrict to one plant. None asks every registered site.
        timeout: Per-plant deadline in seconds. A plant past it is reported
            unavailable; the others still answer.
        sort_key: Record field holding the timestamp. Records missing it
            sort first.

    Raises:
        UnknownSiteError: if site_id is given and not registered.
    """
    if site_id:
        if site_id not in sites:
            raise UnknownSiteError(site_id, sorted(sites))
        selected = {site_id: sites[site_id]}
    else:
        selected = dict(sites)

    result: FederatedResult[S] = FederatedResult(queried=list(selected))

    async def _one(sid: str, site: S) -> list[dict[str, Any]] | str:
        try:
            if timeout is None:
                return await fetch(sid, site)
            return await asyncio.wait_for(fetch(sid, site), timeout)
        except asyncio.TimeoutError:
            return f"did not answer within {timeout:g}s"
        except SiteUnavailable as exc:
            return str(exc) or "unavailable"
        except Exception as exc:  # isolate every per-plant failure
            return f"{type(exc).__name__}: {exc}"

    answers = await asyncio.gather(*(_one(s, v) for s, v in selected.items()))

    for sid, answer in zip(selected, answers):
        if isinstance(answer, str):
            result.unavailable[sid] = answer
            continue
        if not isinstance(answer, list):
            result.unavailable[sid] = (
                f"returned {type(answer).__name__}, expected a list of records"
            )
            continue
        for record in answer:
            record.setdefault("site_id", sid)
            result.records.append(record)

    result.records.sort(key=lambda r: str(r.get(sort_key) or ""))
    return result
