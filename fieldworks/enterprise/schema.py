"""Pydantic schema for enterprise.yaml — the plant registry (spec Part V).

Structural rules live here and fail at load time: every required field
present, site_id unique across the whole file (not just within a region),
region ids unique. Rules that need other files — each topology_file
existing and declaring a matching facility.site_id — live in validator.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class SiteConfig(BaseModel):
    site_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    topology_file: str = Field(min_length=1)
    chat_ui_url: str = Field(min_length=1)
    # Only federated read uses it, to reach the plant's audit history. A site
    # without it is left out of federated reads and reported as unavailable.
    aggregator_url: str | None = None


class RegionConfig(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    # Required but may be empty: a region can be declared before its first
    # plant comes online.
    sites: list[SiteConfig]


class EnterpriseInfo(BaseModel):
    name: str = Field(min_length=1)


class RegisteredSite(SiteConfig):
    """A site flattened out of its region, for lookups by site_id."""

    region_id: str
    region_name: str


class EnterpriseConfig(BaseModel):
    enterprise: EnterpriseInfo
    regions: list[RegionConfig]

    @model_validator(mode="after")
    def _unique_ids(self) -> "EnterpriseConfig":
        region_ids = [r.id for r in self.regions]
        dup_regions = sorted({i for i in region_ids if region_ids.count(i) > 1})
        if dup_regions:
            raise ValueError(f"duplicate region id(s): {dup_regions}")

        seen: dict[str, str] = {}
        for region in self.regions:
            for site in region.sites:
                if site.site_id in seen:
                    raise ValueError(
                        f"duplicate site_id {site.site_id!r} in regions "
                        f"{seen[site.site_id]!r} and {region.id!r} — site_id "
                        "must be unique across the whole enterprise"
                    )
                seen[site.site_id] = region.id
        return self

    def sites(self) -> dict[str, RegisteredSite]:
        """Every site keyed by site_id, in file order."""
        return {
            site.site_id: RegisteredSite(
                **site.model_dump(), region_id=region.id, region_name=region.name
            )
            for region in self.regions
            for site in region.sites
        }

    def get_site(self, site_id: str) -> RegisteredSite | None:
        return self.sites().get(site_id)
