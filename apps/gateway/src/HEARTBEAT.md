# AutoSwarm Heartbeat Configuration

## Schedule
- Interval: 30 minutes
- Active hours: 24/7

## Data Sources
- CRM: Pending contacts, follow-ups, new leads
- GitHub: Open PRs, new issues, failed CI runs
- Support: Open tickets, escalations, SLA breaches

## Event Types
- enemy_wave: New batch of tasks requiring attention
- alert: Urgent item needing immediate review
- report: Summary of completed activities
