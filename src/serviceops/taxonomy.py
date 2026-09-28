"""Service desk taxonomy, SLA policy and the classification aliases the quality gate repairs.

Everything the simulator, the quality checks and the SQL layer agree on lives here, so a
category or priority is defined exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass

SNAPSHOT = "2026-06-30 23:59:59"  # the export is taken at this instant
START = "2024-01-01"
END = "2026-06-30"
SLA_GOAL_PCT = 90.0  # service-level objective: share of scored tickets resolved within target


@dataclass(frozen=True)
class Priority:
    code: str
    name: str
    response_target_hours: float
    resolution_target_hours: float
    share: float


# Calendar-hour targets (24x7 desk). Resolution clock: opened -> resolved.
PRIORITIES = [
    Priority("P1", "Critical", 0.25, 4, 0.03),
    Priority("P2", "High", 1, 8, 0.14),
    Priority("P3", "Medium", 4, 24, 0.48),
    Priority("P4", "Low", 8, 72, 0.35),
]
PRIORITY_BY_NAME = {p.name: p for p in PRIORITIES}


@dataclass(frozen=True)
class Category:
    name: str
    group: str
    share: float
    subcategories: tuple[str, ...]
    work_factor: float  # median hands-on time as a fraction of the SLA target
    hop_rate: float  # mean reassignments between groups
    wait_prob: float  # chance the ticket waits on a third party (approval, carrier, vendor)
    wait_hours: float  # mean length of that wait
    wait_reason: str


CATEGORIES = [
    Category("Access & Identity", "Identity & Access", 0.19,
             ("Permission request", "Account locked", "MFA enrolment", "Shared drive access",
              "SSO error"),
             0.30, 0.85, 0.24, 22.0, "Awaiting manager approval"),
    Category("Network & VPN", "Network Operations", 0.15,
             ("VPN will not connect", "Slow connection", "Wi-Fi drop-outs", "Firewall rule request",
              "Site outage"),
             0.34, 0.90, 0.18, 26.0, "Awaiting carrier / vendor"),
    Category("Software", "Desktop Support", 0.18,
             ("Install request", "Application crash", "Licence request", "Update failure"),
             0.26, 0.25, 0.05, 10.0, "Awaiting vendor patch"),
    Category("Hardware", "Desktop Support", 0.13,
             ("Laptop fault", "Monitor / dock", "Peripheral request", "Battery failure"),
             0.28, 0.20, 0.07, 18.0, "Awaiting parts"),
    Category("Email & Collaboration", "Collaboration", 0.14,
             ("Mailbox full", "Shared mailbox access", "Teams meeting issue", "Calendar sync"),
             0.22, 0.20, 0.03, 8.0, "Awaiting vendor"),
    Category("Printing", "Desktop Support", 0.08,
             ("Printer offline", "Driver install", "Scan to email", "Toner / paper jam"),
             0.20, 0.10, 0.02, 12.0, "Awaiting parts"),
    Category("Onboarding", "Service Desk", 0.08,
             ("New starter setup", "Leaver deprovisioning", "Role change"),
             0.24, 0.30, 0.04, 16.0, "Awaiting HR details"),
    Category("Security", "Security Operations", 0.05,
             ("Phishing report", "Malware alert", "Lost device", "Suspicious sign-in"),
             0.24, 0.35, 0.04, 6.0, "Awaiting user"),
]
CATEGORY_BY_NAME = {c.name: c for c in CATEGORIES}
SUBCATEGORY_TO_CATEGORY = {s: c.name for c in CATEGORIES for s in c.subcategories}

GROUP_AGENTS = {
    "Service Desk": ["A. Singh", "M. Chen", "J. Okafor", "R. Patel", "S. Ahmed", "L. Nguyen"],
    "Desktop Support": ["D. Rossi", "K. Brown", "T. Martin", "E. Walsh", "P. Kaur"],
    "Identity & Access": ["F. Haddad", "C. Lopez", "B. Kim"],
    "Network Operations": ["G. Novak", "H. Silva", "V. Ivanova"],
    "Collaboration": ["N. Farah", "O. Byrne"],
    "Security Operations": ["Y. Tanaka", "Z. Mensah"],
}
CHANNELS = [("Portal", 0.46), ("Email", 0.24), ("Phone", 0.18), ("Chat", 0.12)]
DEPARTMENTS = [("Operations", 0.22), ("Sales", 0.17), ("Finance", 0.12), ("Customer Care", 0.16),
               ("Engineering", 0.13), ("HR", 0.06), ("Marketing", 0.08), ("Executive", 0.06)]
SITES = [("Toronto", 0.38), ("Mississauga", 0.20), ("Waterloo", 0.16), ("Ottawa", 0.14),
         ("Remote", 0.12)]

# Labels that older forms, email parsing and a retired tool write instead of the canonical
# names. The quality gate maps these back; anything not listed is quarantined.
CATEGORY_ALIASES = {
    "access & identity": "Access & Identity", "identity/access": "Access & Identity",
    "iam": "Access & Identity", "access": "Access & Identity", "password": "Access & Identity",
    "network & vpn": "Network & VPN", "network": "Network & VPN", "vpn": "Network & VPN",
    "network/vpn": "Network & VPN",
    "software": "Software", "application": "Software", "sw": "Software",
    "hardware": "Hardware", "hardware issue": "Hardware", "hw": "Hardware",
    "email & collaboration": "Email & Collaboration", "email": "Email & Collaboration",
    "outlook": "Email & Collaboration", "teams": "Email & Collaboration",
    "printing": "Printing", "printer": "Printing", "print": "Printing",
    "onboarding": "Onboarding", "new starter": "Onboarding",
    "security": "Security", "infosec": "Security",
}
PRIORITY_ALIASES = {
    "critical": "Critical", "p1": "Critical", "1 - critical": "Critical", "crit": "Critical",
    "high": "High", "p2": "High", "2 - high": "High",
    "medium": "Medium", "p3": "Medium", "3 - medium": "Medium", "med": "Medium",
    "low": "Low", "p4": "Low", "4 - low": "Low",
}
