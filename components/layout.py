"""Top-level layout: sidebar + topbar + content area."""

from __future__ import annotations

from dash import dcc, html, page_registry

# Sidebar grouping declared independently of Dash's page registry so we keep
# a stable enterprise look-and-feel even if pages are added in any order.
NAV_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Overview",
        [("Executive Cockpit", "/")],
    ),
    (
        "Inventory",
        [
            ("Fleet Inventory", "/inventory/fleet"),
            ("DB Inventory & Capacity", "/db/inventory"),
            ("PDB Inventory", "/db/pdbs"),
        ],
    ),
    (
        "DB Resource Analytics",
        [
            ("DB Memory Analytics", "/db/memory"),
            ("DB Memory Cluster Rollup", "/db/memory-cluster"),
            ("DB CPU Analytics", "/db/cpu"),
            ("DB IOPS Analytics", "/db/iops"),
            ("DB Throughput Analytics", "/db/throughput"),
        ],
    ),
    (
        "OS Resource Analytics",
        [
            ("OS CPU Analytics", "/os/cpu"),
            ("OS Memory Analytics", "/os/memory"),
            ("HugePages Analytics", "/os/hugepages"),
            ("Filesystem Analytics", "/os/filesystem"),
        ],
    ),
    (
        "Storage Analytics",
        [
            ("ASM Analytics", "/storage/asm"),
            ("Cell Inventory", "/storage/cells"),
        ],
    ),
    (
        "Explore",
        [("Raw Data Explorer", "/explore/raw")],
    ),
]


def sidebar() -> html.Div:
    """Render the dark sidebar with grouped navigation."""

    sections = []
    for group_label, items in NAV_GROUPS:
        links = [
            dcc.Link(label, href=href, className="nav-link")
            for label, href in items
        ]
        sections.append(
            html.Div(
                [
                    html.Div(group_label, className="nav-group-title"),
                    html.Div(links, className="nav-group-links"),
                ],
                className="nav-group",
            )
        )

    return html.Div(
        [
            html.Div(
                [
                    html.Div("EXADATA", className="brand-eyebrow"),
                    html.Div("Resource Intelligence", className="brand-title"),
                ],
                className="brand",
            ),
            html.Div(sections, className="nav-sections"),
            html.Div(
                # TODO: surface app-level auth/RBAC user chip here once a
                # reverse-proxy header or OIDC/SAML integration is wired in.
                "Local-only viewer",
                className="sidebar-footer",
            ),
        ],
        className="sidebar",
    )


def topbar(global_cluster_options: list[dict[str, str]]) -> html.Div:
    """Render the topbar with the global cluster filter."""

    return html.Div(
        [
            html.Div(
                [
                    html.Div("Enterprise Analytics", className="topbar-eyebrow"),
                    html.Div(id="page-title", className="topbar-title"),
                ],
                className="topbar-left",
            ),
            html.Div(
                [
                    html.Label("Cluster", className="topbar-filter-label"),
                    dcc.Dropdown(
                        id="global-cluster-filter",
                        options=global_cluster_options,
                        value=[],
                        multi=True,
                        placeholder="All clusters",
                        className="topbar-filter",
                    ),
                ],
                className="topbar-right",
            ),
        ],
        className="topbar",
    )


def app_layout(page_container, global_cluster_options: list[dict[str, str]]) -> html.Div:
    """Compose the global layout used by ``dash_app.py``."""

    return html.Div(
        [
            dcc.Location(id="url", refresh=False),
            dcc.Store(id="global-filter-state", data={"clusters": []}),
            sidebar(),
            html.Div(
                [
                    topbar(global_cluster_options),
                    html.Div(page_container, className="page-content"),
                ],
                className="main-area",
            ),
        ],
        className="app-shell",
    )


def page_title_from_path(pathname: str) -> str:
    """Map a URL path to the friendly page title shown in the topbar."""

    for _, items in NAV_GROUPS:
        for label, href in items:
            if href == pathname:
                return label
    # Deep-link routes (/cluster/<x>, /db/<name>, /host/<name>) will land
    # here in future phases. For now, surface the path so users see it.
    return "Exadata Resource Intelligence"
