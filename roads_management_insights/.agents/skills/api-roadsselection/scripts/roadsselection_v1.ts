/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Roads Selection API v1 Reference Client for TypeScript / Node.js.
 *
 * Provides an enterprise, strongly-typed asynchronous client for managing
 * SelectedRoute resources within the Roads Selection API (Google Maps Platform).
 *
 * Runs natively in Node.js 22+ with: node --experimental-strip-types
 *
 * Supported RPC Methods:
 *   1. CreateSelectedRoute (POST /selection/v1/projects/{project}/selectedRoutes)
 *   2. BatchCreateSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchCreate)
 *   3. GetSelectedRoute (GET /selection/v1/projects/{project}/selectedRoutes/{id})
 *   4. UpdateSelectedRoute (PATCH /selection/v1/projects/{project}/selectedRoutes/{id}?updateMask=...)
 *   5. BatchUpdateSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchUpdate)
 *   6. ListSelectedRoutes (GET /selection/v1/projects/{project}/selectedRoutes)
 *   7. DeleteSelectedRoute (DELETE /selection/v1/projects/{project}/selectedRoutes/{id})
 *   8. BatchDeleteSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchDelete)
 */

/**
 * Geographic coordinates in decimal degrees (WGS84).
 */
export interface LatLng {
  /** Latitude in degrees [-90.0, 90.0]. */
  latitude: number;
  /** Longitude in degrees [-180.0, 180.0]. */
  longitude: number;
}

/**
 * Dynamic route geometry definition based on real-time routing graph.
 */
export interface DynamicRoute {
  /** Starting waypoint for the route corridor. */
  origin: LatLng;
  /** Ending waypoint for the route corridor. */
  destination: LatLng;
  /** Optional intermediate waypoints (maximum 25). */
  intermediates?: LatLng[];
}

/**
 * Full SelectedRoute resource representation returned by the Roads Selection API.
 */
export interface SelectedRoute {
  /** Canonical resource name ('projects/{project}/selectedRoutes/{id}'). */
  name: string;
  /** Human-readable display label (max 100 characters). */
  displayName?: string;
  /** Dynamic waypoint geometry defining the corridor. */
  dynamicRoute?: DynamicRoute;
  /** Key-value metadata pairs used for BigQuery clustering and stream filtering (max 10). */
  routeAttributes?: Record<string, string>;
  /** Output-only lifecycle state (e.g. 'STATE_RUNNING', 'STATE_VALIDATING', 'STATE_INVALID'). */
  state?: string;
  /** Output-only validation error reason if state is 'STATE_INVALID'. */
  validationError?: string;
  /** Output-only creation timestamp (RFC 3339 format). */
  createTime?: string;
  /** Output-only last modification timestamp (RFC 3339 format). */
  updateTime?: string;
}

/**
 * Paginated response structure returned by ListSelectedRoutes.
 */
export interface ListSelectedRoutesResponse {
  /** Array of SelectedRoute resources on the requested page. */
  selectedRoutes?: SelectedRoute[];
  /** Pagination continuation token for subsequent page retrieval. */
  nextPageToken?: string;
}

/**
 * Response structure returned by BatchCreateSelectedRoutes.
 */
export interface BatchCreateResponse {
  /** Array of provisioned SelectedRoute resources. */
  selectedRoutes: SelectedRoute[];
}

/**
 * Response structure returned by BatchUpdateSelectedRoutes.
 */
export interface BatchUpdateResponse {
  /** Array of modified SelectedRoute resources. */
  selectedRoutes: SelectedRoute[];
}

/**
 * Input parameters for creating a new SelectedRoute.
 */
export interface CreateRouteInput {
  /** Unique route ID (4-63 characters, [a-zA-Z0-9-], no underscores). */
  routeId: string;
  /** Human-readable label (max 100 characters). */
  displayName: string;
  /** Starting coordinate. */
  origin: LatLng;
  /** Ending coordinate. */
  destination: LatLng;
  /** Optional intermediate waypoints (max 25). */
  intermediates?: LatLng[];
  /** Optional metadata tags (max 10 pairs, keys must not start with 'goog'). */
  attributes?: Record<string, string>;
}

/**
 * Input parameters for updating an existing SelectedRoute via PATCH.
 */
export interface UpdateRouteInput {
  /** Target route identifier or resource path. */
  routeId: string;
  /** Updated human-readable label. */
  displayName?: string;
  /** Updated dynamic geometry definition. */
  dynamicRoute?: DynamicRoute;
  /** Updated metadata attributes map. */
  attributes?: Record<string, string>;
  /** Optional explicit FieldMask string (e.g. 'displayName,routeAttributes'). */
  updateMask?: string;
}

/**
 * Client initialization configuration options.
 */
export interface RoadsSelectionClientOptions {
  /** Google Cloud Project ID owning the routes. */
  projectId: string;
  /** Optional GoogleAuth instance or pre-fetched access token string. */
  auth?: any;
  /** Optional base API URL override (defaults to https://roads.googleapis.com/selection/v1). */
  baseUrl?: string;
  /** Optional billing project ID passed via X-Goog-User-Project (defaults to projectId). */
  quotaProjectId?: string;
}

/**
 * Validates routeAttributes dictionary according to the proto specification.
 *
 * @param attributes Key-value string map representing route metadata.
 * @throws {TypeError} If attributes is not an object or contains non-string values.
 * @throws {Error} If key count exceeds 10, byte lengths exceed 100 bytes UTF-8, or key starts with 'goog'.
 */
export function validateRouteAttributes(attributes: Record<string, string>): void {
  if (typeof attributes !== 'object' || attributes === null) {
    throw new TypeError('routeAttributes must be an object');
  }
  const keys = Object.keys(attributes);
  if (keys.length > 10) {
    throw new Error(`routeAttributes cannot exceed 10 entries (got ${keys.length})`);
  }
  for (const k of keys) {
    const v = attributes[k];
    if (typeof k !== 'string' || typeof v !== 'string') {
      throw new TypeError(`Attribute key/value must be strings: ${k}=${v}`);
    }
    const kBytes = Buffer.byteLength(k, 'utf8');
    const vBytes = Buffer.byteLength(v, 'utf8');
    if (kBytes < 1 || kBytes > 100) {
      throw new Error(`Attribute key '${k}' must be 1-100 bytes UTF-8 (got ${kBytes} bytes)`);
    }
    if (vBytes > 100) {
      throw new Error(`Attribute value for '${k}' exceeds 100 bytes UTF-8 (got ${vBytes} bytes)`);
    }
    if (k.startsWith('goog')) {
      throw new Error(`Attribute key '${k}' cannot start with reserved prefix 'goog'`);
    }
  }
}

/**
 * Enterprise Reference TypeScript Client for the Roads Selection API v1.
 */
export class RoadsSelectionClient {
  private projectId: string;
  private quotaProjectId: string;
  private baseUrl: string;
  private auth: any;

  /**
   * Initializes a new RoadsSelectionClient instance.
   *
   * @param options Configuration options including projectId and optional credentials.
   */
  constructor(options: RoadsSelectionClientOptions) {
    this.projectId = options.projectId;
    this.quotaProjectId = options.quotaProjectId || options.projectId;
    this.baseUrl = (
      options.baseUrl ||
      process.env.ROADS_SELECTION_BASE_URL ||
      'https://roads.googleapis.com/selection/v1'
    ).replace(/\/$/, '');
    this.auth = options.auth;
  }

  /**
   * Resolves authentication headers including OAuth 2.0 Bearer token and X-Goog-User-Project.
   *
   * @returns Header dictionary for HTTP requests.
   */
  private async getAuthHeaders(): Promise<Record<string, string>> {
    let token = typeof this.auth === 'string' ? this.auth : 'mock-token';
    if (!this.auth) {
      try {
        // Dynamic import enables running in environments without google-auth-library installed
        // @ts-ignore
        const authModule = await import('google-auth-library');
        const GoogleAuth = authModule.GoogleAuth || authModule.default?.GoogleAuth;
        if (GoogleAuth) {
          this.auth = new GoogleAuth({
            scopes: ['https://www.googleapis.com/auth/cloud-platform'],
          });
        }
      } catch {
        token = process.env.GOOGLE_OAUTH_ACCESS_TOKEN || 'mock-token';
      }
    }
    if (this.auth && typeof this.auth.getClient === 'function') {
      const client = await this.auth.getClient();
      const tokenRes = await client.getAccessToken();
      token = tokenRes.token || token;
    }
    return {
      Authorization: `Bearer ${token}`,
      'X-Goog-User-Project': this.quotaProjectId,
      'Content-Type': 'application/json',
    };
  }

  // ---------------------------------------------------------------------------
  // Core CRUD Operations
  // ---------------------------------------------------------------------------

  /**
   * Creates a single SelectedRoute resource and initiates telemetry scheduling.
   *
   * RPC: CreateSelectedRoute (POST /selection/v1/projects/{project}/selectedRoutes)
   *
   * @param input Route configuration parameters.
   * @returns Created SelectedRoute resource definition.
   * @throws {Error} If creation fails or parameters violate proto limits.
   */
  async createSelectedRoute(input: CreateRouteInput): Promise<SelectedRoute> {
    if (input.displayName && Buffer.byteLength(input.displayName, 'utf8') > 100) {
      throw new Error(`displayName exceeds 100 bytes UTF-8 limit (got ${Buffer.byteLength(input.displayName, 'utf8')} bytes)`);
    }
    if (input.attributes) {
      validateRouteAttributes(input.attributes);
    }
    const dynamicRoute: DynamicRoute = {
      origin: input.origin,
      destination: input.destination,
    };
    if (input.intermediates) {
      if (input.intermediates.length > 25) {
        throw new Error('intermediates cannot exceed 25 waypoints');
      }
      dynamicRoute.intermediates = input.intermediates;
    }

    const payload: Partial<SelectedRoute> = {
      displayName: input.displayName,
      dynamicRoute,
    };
    if (input.attributes) {
      payload.routeAttributes = input.attributes;
    }

    const headers = await this.getAuthHeaders();
    const url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes?selectedRouteId=${encodeURIComponent(input.routeId)}`;

    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`createSelectedRoute failed [${res.status}]: ${await res.text()}`);
    }
    return (await res.json()) as SelectedRoute;
  }

  /**
   * Retrieves a SelectedRoute by route ID or full resource name.
   *
   * RPC: GetSelectedRoute (GET /selection/v1/projects/{project}/selectedRoutes/{id})
   *
   * @param routeId Route identifier (e.g. 'corridor-market-st') or full resource path.
   * @returns The fetched SelectedRoute object.
   * @throws {Error} If the route does not exist or fetch fails.
   */
  async getSelectedRoute(routeId: string): Promise<SelectedRoute> {
    const cleanId = routeId.split('/').pop()!;
    const headers = await this.getAuthHeaders();
    const url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes/${cleanId}`;

    const res = await fetch(url, { method: 'GET', headers });
    if (!res.ok) {
      throw new Error(`getSelectedRoute failed [${res.status}]: ${await res.text()}`);
    }
    return (await res.json()) as SelectedRoute;
  }

  /**
   * Lists a single page of SelectedRoutes for the project.
   *
   * RPC: ListSelectedRoutes (GET /selection/v1/projects/{project}/selectedRoutes)
   *
   * @param pageSize Maximum routes per page (default 100, max 5,000).
   * @param pageToken Continuation token from a prior list call.
   * @returns Page result containing selectedRoutes array and optional nextPageToken.
   */
  async listSelectedRoutes(
    pageSize: number = 100,
    pageToken?: string
  ): Promise<ListSelectedRoutesResponse> {
    const headers = await this.getAuthHeaders();
    let url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes?pageSize=${pageSize}`;
    if (pageToken) url += `&pageToken=${encodeURIComponent(pageToken)}`;

    const res = await fetch(url, { method: 'GET', headers });
    if (!res.ok) {
      throw new Error(`listSelectedRoutes failed [${res.status}]: ${await res.text()}`);
    }
    return (await res.json()) as ListSelectedRoutesResponse;
  }

  /**
   * Transparent async iterator that yields all SelectedRoutes across all pages.
   *
   * @param pageSize Number of routes to request per underlying page fetch (default 500).
   * @yields Each SelectedRoute object in the project.
   *
   * @example
   * for await (const route of client.listAllSelectedRoutes()) {
   *   console.log(route.displayName);
   * }
   */
  async *listAllSelectedRoutes(pageSize: number = 500): AsyncGenerator<SelectedRoute, void, unknown> {
    let pageToken: string | undefined = undefined;
    while (true) {
      const page = await this.listSelectedRoutes(pageSize, pageToken);
      const routes = page.selectedRoutes || [];
      for (const r of routes) {
        yield r;
      }
      pageToken = page.nextPageToken;
      if (!pageToken || routes.length === 0) {
        break;
      }
    }
  }

  /**
   * Deletes a SelectedRoute resource and halts telemetry caching.
   *
   * RPC: DeleteSelectedRoute (DELETE /selection/v1/projects/{project}/selectedRoutes/{id})
   *
   * @param routeId Route ID or full resource name to delete.
   * @throws {Error} If deletion fails.
   */
  async deleteSelectedRoute(routeId: string): Promise<void> {
    const cleanId = routeId.split('/').pop()!;
    const headers = await this.getAuthHeaders();
    const url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes/${cleanId}`;

    const res = await fetch(url, { method: 'DELETE', headers });
    if (!res.ok) {
      throw new Error(`deleteSelectedRoute failed [${res.status}]: ${await res.text()}`);
    }
  }

  // ---------------------------------------------------------------------------
  // Updates & FieldMask Operations
  // ---------------------------------------------------------------------------

  /**
   * Natively updates specified route fields in-place using PATCH and FieldMask.
   *
   * RPC: UpdateSelectedRoute (PATCH /selection/v1/projects/{project}/selectedRoutes/{id})
   *
   * @param input Update parameters including routeId, fields to modify, and optional updateMask.
   * @returns The updated SelectedRoute resource.
   * @throws {Error} If update fails or no fields were specified.
   */
  async updateSelectedRoute(input: UpdateRouteInput): Promise<SelectedRoute> {
    const cleanId = input.routeId.split('/').pop()!;
    const payload: Partial<SelectedRoute> = {
      name: `projects/${this.projectId}/selectedRoutes/${cleanId}`,
    };
    const computedMaskFields: string[] = [];

    if (input.displayName !== undefined) {
      payload.displayName = input.displayName;
      computedMaskFields.push('displayName');
    }
    if (input.dynamicRoute !== undefined) {
      payload.dynamicRoute = input.dynamicRoute;
      computedMaskFields.push('dynamicRoute');
    }
    if (input.attributes !== undefined) {
      validateRouteAttributes(input.attributes);
      payload.routeAttributes = input.attributes;
      computedMaskFields.push('routeAttributes');
    }

    const mask = input.updateMask || computedMaskFields.join(',');
    if (!mask) {
      throw new Error('No fields specified to update in updateSelectedRoute');
    }

    const headers = await this.getAuthHeaders();
    const url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes/${cleanId}?updateMask=${encodeURIComponent(mask)}`;

    const res = await fetch(url, {
      method: 'PATCH',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`updateSelectedRoute failed [${res.status}]: ${await res.text()}`);
    }
    return (await res.json()) as SelectedRoute;
  }

  // ---------------------------------------------------------------------------
  // Batch Operations (up to 1,000 routes)
  // ---------------------------------------------------------------------------

  /**
   * Atomically provisions up to 1,000 SelectedRoutes in a single API round-trip.
   *
   * RPC: BatchCreateSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchCreate)
   *
   * @param items Array of route configuration items (maximum 1,000).
   * @returns BatchCreateResponse containing the array of created routes.
   * @throws {Error} If item count exceeds 1,000 or batch creation fails.
   */
  async batchCreateSelectedRoutes(items: CreateRouteInput[]): Promise<BatchCreateResponse> {
    if (items.length > 1000) {
      throw new Error(`batchCreate exceeds maximum 1,000 routes limit (got ${items.length})`);
    }

    const requestsPayload = items.map((item) => {
      if (item.attributes) validateRouteAttributes(item.attributes);
      return {
        parent: `projects/${this.projectId}`,
        selectedRouteId: item.routeId,
        selectedRoute: {
          displayName: item.displayName,
          dynamicRoute: { origin: item.origin, destination: item.destination },
          routeAttributes: item.attributes || {},
        },
      };
    });

    const headers = await this.getAuthHeaders();
    const url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes:batchCreate`;
    const payload = {
      parent: `projects/${this.projectId}`,
      requests: requestsPayload,
    };

    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`batchCreateSelectedRoutes failed [${res.status}]: ${await res.text()}`);
    }
    return (await res.json()) as BatchCreateResponse;
  }

  /**
   * Updates up to 1,000 SelectedRoutes in a single API round-trip.
   *
   * RPC: BatchUpdateSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchUpdate)
   *
   * @param updates Array of route updates (maximum 1,000).
   * @param defaultUpdateMask Optional top-level FieldMask applied across all updates.
   * @returns BatchUpdateResponse containing array of modified routes.
   * @throws {Error} If update count exceeds 1,000 or batch update fails.
   */
  async batchUpdateSelectedRoutes(
    updates: UpdateRouteInput[],
    defaultUpdateMask?: string
  ): Promise<BatchUpdateResponse> {
    if (updates.length > 1000) {
      throw new Error(`batchUpdate exceeds maximum 1,000 routes limit (got ${updates.length})`);
    }

    const requestsPayload = updates.map((item) => {
      const rid = item.routeId.split('/').pop()!;
      const sr: Partial<SelectedRoute> = {
        name: `projects/${this.projectId}/selectedRoutes/${rid}`,
      };
      if (item.displayName !== undefined) sr.displayName = item.displayName;
      if (item.attributes !== undefined) {
        validateRouteAttributes(item.attributes);
        sr.routeAttributes = item.attributes;
      }
      return {
        selectedRoute: sr,
        updateMask: item.updateMask || defaultUpdateMask || 'displayName,routeAttributes',
      };
    });

    const headers = await this.getAuthHeaders();
    const url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes:batchUpdate`;
    const payload: any = {
      parent: `projects/${this.projectId}`,
      requests: requestsPayload,
    };
    if (defaultUpdateMask) {
      payload.updateMask = defaultUpdateMask;
    }

    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`batchUpdateSelectedRoutes failed [${res.status}]: ${await res.text()}`);
    }
    return (await res.json()) as BatchUpdateResponse;
  }

  /**
   * Atomically deletes up to 1,000 SelectedRoutes in a single API round-trip.
   *
   * RPC: BatchDeleteSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchDelete)
   *
   * @param routeIds Array of route identifiers or resource names (maximum 1,000).
   * @throws {Error} If count exceeds 1,000 or batch deletion fails.
   */
  async batchDeleteSelectedRoutes(routeIds: string[]): Promise<void> {
    if (routeIds.length > 1000) {
      throw new Error(`batchDelete exceeds maximum 1,000 routes limit (got ${routeIds.length})`);
    }

    const fullNames = routeIds.map((r) =>
      r.startsWith('projects/') ? r : `projects/${this.projectId}/selectedRoutes/${r}`
    );
    const headers = await this.getAuthHeaders();
    const url = `${this.baseUrl}/projects/${this.projectId}/selectedRoutes:batchDelete`;
    const payload = {
      parent: `projects/${this.projectId}`,
      names: fullNames,
    };

    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(`batchDeleteSelectedRoutes failed [${res.status}]: ${await res.text()}`);
    }
  }

  // ---------------------------------------------------------------------------
  // High-Level Utilities
  // ---------------------------------------------------------------------------

  /**
   * Polls route status asynchronously until it reaches the target lifecycle state.
   *
   * @param routeId Route identifier to monitor.
   * @param targetState Expected lifecycle state (defaults to 'STATE_RUNNING').
   * @param timeoutSeconds Maximum duration in seconds before throwing a timeout.
   * @param pollIntervalMs Polling interval in milliseconds (defaults to 2,000ms).
   * @returns Final SelectedRoute object when targetState is reached.
   * @throws {Error} If route enters 'STATE_INVALID' or times out.
   */
  async waitForRouteState(
    routeId: string,
    targetState: string = 'STATE_RUNNING',
    timeoutSeconds: number = 30,
    pollIntervalMs: number = 2000
  ): Promise<SelectedRoute> {
    const startTime = Date.now();
    while (Date.now() - startTime < timeoutSeconds * 1000) {
      const route = await this.getSelectedRoute(routeId);
      const state = route.state || 'STATE_UNSPECIFIED';
      if (state === targetState) {
        return route;
      }
      if (state === 'STATE_INVALID') {
        const err = route.validationError || 'VALIDATION_ERROR_UNSPECIFIED';
        throw new Error(`Route '${routeId}' entered STATE_INVALID: ${err}`);
      }
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
    throw new Error(`Route '${routeId}' did not reach ${targetState} within ${timeoutSeconds}s`);
  }
}
