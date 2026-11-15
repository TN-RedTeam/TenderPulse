import type {
  CollectionRun, FollowUpStatus, Me, Opportunity, OpportunityFilters, OpportunityList, Profile, ProfileInput,
  Tenant, TenantCreated,
} from "./types";

const STORAGE_KEY = "tenderpulse.apiKey";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function loadApiKey(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveApiKey(apiKey: string): void {
  try {
    if (apiKey) {
      window.localStorage.setItem(STORAGE_KEY, apiKey);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // Stockage indisponible (navigation privée) : la clé reste en mémoire pour la session.
  }
}

function describeError(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const entry = item as { loc?: unknown[]; msg?: string };
          const field = Array.isArray(entry.loc) ? String(entry.loc[entry.loc.length - 1]) : "";
          return field ? `${field} : ${entry.msg ?? "valeur invalide"}` : entry.msg ?? "valeur invalide";
        })
        .join(" · ");
    }
  }
  return fallback;
}

export class ApiClient {
  private readonly apiKey: string;

  constructor(apiKey: string) {
    this.apiKey = apiKey;
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set("X-API-Key", this.apiKey);
    if (init.body) {
      headers.set("Content-Type", "application/json");
    }
    let response: Response;
    try {
      response = await fetch(`/api${path}`, { method: init.method, body: init.body, headers });
    } catch {
      throw new ApiError(0, "Serveur injoignable. Vérifiez que le backend est démarré.");
    }
    if (!response.ok) {
      const body: unknown = await response.json().catch(() => null);
      throw new ApiError(response.status, describeError(body, `Erreur ${response.status}`));
    }
    return response;
  }

  private async json<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.request(path, init);
    return (await response.json()) as T;
  }

  me(): Promise<Me> {
    return this.json<Me>("/me");
  }

  listTenants(): Promise<Tenant[]> {
    return this.json<Tenant[]>("/tenants");
  }

  createTenant(name: string, contactEmail: string | null): Promise<TenantCreated> {
    return this.json<TenantCreated>("/tenants", {
      method: "POST",
      body: JSON.stringify({ name, contact_email: contactEmail }),
    });
  }

  listProfiles(tenantId: string): Promise<Profile[]> {
    return this.json<Profile[]>(`/tenants/${tenantId}/profiles`);
  }

  createProfile(tenantId: string, profile: ProfileInput): Promise<Profile> {
    return this.json<Profile>(`/tenants/${tenantId}/profiles`, { method: "POST", body: JSON.stringify(profile) });
  }

  updateProfile(tenantId: string, profileId: string, profile: ProfileInput): Promise<Profile> {
    return this.json<Profile>(`/tenants/${tenantId}/profiles/${profileId}`, {
      method: "PUT",
      body: JSON.stringify(profile),
    });
  }

  async deleteProfile(tenantId: string, profileId: string): Promise<void> {
    await this.request(`/tenants/${tenantId}/profiles/${profileId}`, { method: "DELETE" });
  }

  listOpportunities(tenantId: string, profileId: string, filters: OpportunityFilters): Promise<OpportunityList> {
    const params = new URLSearchParams({ limit: "200" });
    if (filters.decision) {
      params.set("decision", filters.decision);
    }
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (filters.includeExpired) {
      params.set("include_expired", "true");
    }
    return this.json<OpportunityList>(`/tenants/${tenantId}/profiles/${profileId}/opportunities?${params.toString()}`);
  }

  updateStatus(tenantId: string, opportunityId: number, status: FollowUpStatus): Promise<Opportunity> {
    return this.json<Opportunity>(`/tenants/${tenantId}/opportunities/${opportunityId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  }

  async digestHtml(tenantId: string, profileId: string, sinceHours: number): Promise<string> {
    const response = await this.request(`/tenants/${tenantId}/profiles/${profileId}/digest?since_hours=${sinceHours}`);
    return response.text();
  }

  startCollection(): Promise<CollectionRun> {
    return this.json<CollectionRun>("/collect", { method: "POST", body: JSON.stringify({}) });
  }

  getRun(runId: number): Promise<CollectionRun> {
    return this.json<CollectionRun>(`/collect/runs/${runId}`);
  }
}
