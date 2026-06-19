# This file is intentionally empty.
# LocalBus is defined in broadcast_bus.py alongside the BroadcastBus ABC.
# In single-instance mode, LocalBus.publish() is a no-op — local delivery
# is handled by DashboardHub.broadcast_event(). This module exists as a
# placeholder for future local-bus-specific extensions if needed.
