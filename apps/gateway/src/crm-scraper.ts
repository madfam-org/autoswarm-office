/**
 * CRM scraper for Phyne-CRM integration.
 *
 * Fetches open leads, overdue activities, and hot leads from the Phyne-CRM
 * tRPC API and converts them into ExternalEvent objects for the HeartbeatService.
 */

interface ExternalEvent {
  source: string;
  type: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

interface TRPCResponse<T = unknown> {
  result?: { data?: T };
}

interface PhyneLead {
  id: string;
  contact_id: string;
  stage_id: string;
  stage_name?: string;
  score?: number;
  status?: string;
}

interface PhyneActivity {
  id: string;
  type: string;
  title: string;
  status?: string;
  due_date?: string;
  entity_type?: string;
  entity_id?: string;
}

export class CRMScraper {
  private readonly baseUrl: string;
  private readonly token: string;

  constructor(baseUrl: string, token: string = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
  }

  async scrape(): Promise<ExternalEvent[]> {
    const events: ExternalEvent[] = [];
    const now = new Date().toISOString();

    try {
      // Fetch open leads
      const leads = await this.fetchLeads("open");
      for (const lead of leads) {
        if (lead.score != null && lead.score > 80) {
          events.push({
            source: "crm",
            type: "hot_lead",
            payload: {
              lead_id: lead.id,
              contact_id: lead.contact_id,
              score: lead.score,
              stage: lead.stage_name ?? lead.stage_id,
            },
            timestamp: now,
          });
        } else {
          events.push({
            source: "crm",
            type: "lead_followup",
            payload: {
              lead_id: lead.id,
              contact_id: lead.contact_id,
              stage: lead.stage_name ?? lead.stage_id,
            },
            timestamp: now,
          });
        }
      }

      // Fetch overdue activities
      const activities = await this.fetchActivities();
      for (const activity of activities) {
        if (this.isOverdue(activity)) {
          events.push({
            source: "crm",
            type: "activity_overdue",
            payload: {
              activity_id: activity.id,
              title: activity.title,
              type: activity.type,
              due_date: activity.due_date,
              entity_type: activity.entity_type,
              entity_id: activity.entity_id,
            },
            timestamp: now,
          });
        }
      }
    } catch (err) {
      console.error("[crm-scraper] CRM scrape failed:", err);
    }

    return events;
  }

  private async fetchLeads(status?: string): Promise<PhyneLead[]> {
    const input = status ? JSON.stringify({ status }) : undefined;
    const url = `${this.baseUrl}/api/trpc/leads.list${input ? `?input=${encodeURIComponent(input)}` : ""}`;

    const response = await fetch(url, {
      headers: this.headers(),
    });

    if (!response.ok) {
      console.error(`[crm-scraper] leads.list returned ${response.status}`);
      return [];
    }

    const json = (await response.json()) as TRPCResponse<PhyneLead[]>;
    return json.result?.data ?? [];
  }

  private async fetchActivities(): Promise<PhyneActivity[]> {
    const url = `${this.baseUrl}/api/trpc/activities.listForEntity?input=${encodeURIComponent(JSON.stringify({ type: "all", id: "" }))}`;

    const response = await fetch(url, {
      headers: this.headers(),
    });

    if (!response.ok) {
      console.error(
        `[crm-scraper] activities.listForEntity returned ${response.status}`
      );
      return [];
    }

    const json = (await response.json()) as TRPCResponse<PhyneActivity[]>;
    return (json.result?.data ?? []).filter(
      (a) => a.status === "pending" || a.status === "overdue"
    );
  }

  private isOverdue(activity: PhyneActivity): boolean {
    if (!activity.due_date) return false;
    return new Date(activity.due_date) < new Date();
  }

  private headers(): Record<string, string> {
    const h: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (this.token) {
      h["Authorization"] = `Bearer ${this.token}`;
    }
    return h;
  }
}
