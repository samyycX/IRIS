from __future__ import annotations

from neo4j import NotificationMinimumSeverity

NEO4J_DRIVER_CONFIG = {
    "notifications_min_severity": NotificationMinimumSeverity.WARNING,
    "warn_notification_severity": NotificationMinimumSeverity.WARNING,
}