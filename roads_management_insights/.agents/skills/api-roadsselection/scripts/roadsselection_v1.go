// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Package roadsselectionv1 provides a zero-dependency standard-library Go
// reference client for the Google Maps Platform Roads Selection API v1
// (https://roads.googleapis.com/selection/v1, Discovery revision 20261101).
//
// Supported RPC Methods:
//  1. CreateSelectedRoute (POST /projects/{project}/selectedRoutes)
//  2. BatchCreateSelectedRoutes (POST /projects/{project}/selectedRoutes:batchCreate)
//  3. GetSelectedRoute (GET /projects/{project}/selectedRoutes/{id})
//  4. UpdateSelectedRoute (PATCH /projects/{project}/selectedRoutes/{id}?updateMask=...)
//  5. BatchUpdateSelectedRoutes (POST /projects/{project}/selectedRoutes:batchUpdate)
//  6. ListSelectedRoutes (GET /projects/{project}/selectedRoutes)
//  7. DeleteSelectedRoute (DELETE /projects/{project}/selectedRoutes/{id})
//  8. BatchDeleteSelectedRoutes (POST /projects/{project}/selectedRoutes:batchDelete)
package roadsselectionv1

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

// DefaultBaseURL is the canonical Roads Selection API v1 REST base endpoint.
const DefaultBaseURL = "https://roads.googleapis.com/selection/v1"

// Lifecycle State enum constants (SelectedRoute.state).
const (
	StateUnspecified = "STATE_UNSPECIFIED"
	StateScheduling  = "STATE_SCHEDULING"
	StateRunning     = "STATE_RUNNING"
	StateDeleting    = "STATE_DELETING"
	StateValidating  = "STATE_VALIDATING"
	StateInvalid     = "STATE_INVALID"
)

// ValidationError enum constants (SelectedRoute.validationError).
const (
	ValidationErrorUnspecified              = "VALIDATION_ERROR_UNSPECIFIED"
	ValidationErrorRouteOutsideJurisdiction = "VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION"
	ValidationErrorLowRoadUsage             = "VALIDATION_ERROR_LOW_ROAD_USAGE"
)

var selectedRouteIDPattern = regexp.MustCompile(`^[a-zA-Z0-9_-]{4,63}$`)

// BoolPtr returns a pointer to the given boolean value for SelectedRoute.DynamicRouting.
func BoolPtr(v bool) *bool {
	return &v
}

// LatLng represents WGS84 geographic coordinates in decimal degrees.
type LatLng struct {
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
}

// DynamicRoute defines origin, destination, and optional intermediate waypoints.
type DynamicRoute struct {
	Origin        LatLng   `json:"origin"`
	Destination   LatLng   `json:"destination"`
	Intermediates []LatLng `json:"intermediates,omitempty"`
}

// SelectedRoute represents a monitored corridor in the Roads Selection API v1.
type SelectedRoute struct {
	Name            string            `json:"name,omitempty"`
	DisplayName     string            `json:"displayName,omitempty"`
	DynamicRoute    *DynamicRoute     `json:"dynamicRoute,omitempty"`
	DynamicRouting  *bool             `json:"dynamicRouting,omitempty"`
	RouteAttributes map[string]string `json:"routeAttributes,omitempty"`
	CreateTime      string            `json:"createTime,omitempty"`
	State           string            `json:"state,omitempty"`
	ValidationError string            `json:"validationError,omitempty"`
}

// CreateSelectedRouteRequest represents a child item inside BatchCreateSelectedRoutesRequest.
type CreateSelectedRouteRequest struct {
	Parent          string        `json:"parent,omitempty"`
	SelectedRouteID string        `json:"selectedRouteId,omitempty"`
	SelectedRoute   SelectedRoute `json:"selectedRoute"`
}

// BatchCreateSelectedRoutesRequest is the JSON request body for selectedRoutes:batchCreate.
// Per Discovery 20261101, top-level parent is bound in the URL path and omitted from the body.
type BatchCreateSelectedRoutesRequest struct {
	Requests []CreateSelectedRouteRequest `json:"requests"`
}

// BatchCreateSelectedRoutesResponse is returned by selectedRoutes:batchCreate.
type BatchCreateSelectedRoutesResponse struct {
	SelectedRoutes []SelectedRoute `json:"selectedRoutes"`
}

// UpdateSelectedRouteRequest represents a child item inside BatchUpdateSelectedRoutesRequest.
type UpdateSelectedRouteRequest struct {
	SelectedRoute SelectedRoute `json:"selectedRoute"`
	UpdateMask    string        `json:"updateMask,omitempty"`
}

// BatchUpdateSelectedRoutesRequest is the JSON request body for selectedRoutes:batchUpdate.
// Per Discovery 20261101, top-level parent is bound in the URL path and omitted from the body.
type BatchUpdateSelectedRoutesRequest struct {
	Requests   []UpdateSelectedRouteRequest `json:"requests"`
	UpdateMask string                       `json:"updateMask,omitempty"`
}

// BatchUpdateSelectedRoutesResponse is returned by selectedRoutes:batchUpdate.
type BatchUpdateSelectedRoutesResponse struct {
	SelectedRoutes []SelectedRoute `json:"selectedRoutes"`
}

// BatchDeleteSelectedRoutesRequest is the JSON request body for selectedRoutes:batchDelete.
// Per Discovery 20261101, top-level parent is bound in the URL path and omitted from the body.
type BatchDeleteSelectedRoutesRequest struct {
	Names []string `json:"names"`
}

// ListSelectedRoutesResponse is returned by GET /projects/{project}/selectedRoutes.
type ListSelectedRoutesResponse struct {
	SelectedRoutes []SelectedRoute `json:"selectedRoutes,omitempty"`
	NextPageToken  string          `json:"nextPageToken,omitempty"`
}

// APIError captures non-2xx HTTP responses from the Roads Selection API.
type APIError struct {
	StatusCode int
	Method     string
	URL        string
	Body       string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("roadsselection %s %s failed [%d]: %s", e.Method, e.URL, e.StatusCode, e.Body)
}

// ValidateSelectedRouteID enforces Discovery 20261101 selectedRouteId constraints:
//   - Empty string "" is allowed (server auto-generates a UUID on creation).
//   - Otherwise must be 4-63 characters matching ^[a-zA-Z0-9_-]{4,63}$.
func ValidateSelectedRouteID(routeID string) error {
	if routeID == "" {
		return nil
	}
	if len(routeID) < 4 || len(routeID) > 63 {
		return fmt.Errorf("selectedRouteId %q must be 4-63 characters (got %d)", routeID, len(routeID))
	}
	if !selectedRouteIDPattern.MatchString(routeID) {
		return fmt.Errorf("selectedRouteId %q contains invalid characters; valid characters are 'a-z', 'A-Z', '0-9', '-', or '_'", routeID)
	}
	return nil
}

// ValidateDisplayName enforces <= 100 Unicode code points on SelectedRoute.displayName.
func ValidateDisplayName(displayName string) error {
	count := utf8.RuneCountInString(displayName)
	if count > 100 {
		return fmt.Errorf("displayName cannot exceed 100 Unicode code points (got %d)", count)
	}
	return nil
}

// ValidateLatLng enforces WGS84 coordinate bounds.
func ValidateLatLng(coord LatLng) error {
	if coord.Latitude < -90.0 || coord.Latitude > 90.0 {
		return fmt.Errorf("latitude %v out of [-90, 90] bounds", coord.Latitude)
	}
	if coord.Longitude < -180.0 || coord.Longitude > 180.0 {
		return fmt.Errorf("longitude %v out of [-180, 180] bounds", coord.Longitude)
	}
	return nil
}

// ValidateDynamicRoute enforces origin, destination, and <= 25 intermediate waypoints.
func ValidateDynamicRoute(dr *DynamicRoute) error {
	if dr == nil {
		return errors.New("dynamicRoute is required")
	}
	if err := ValidateLatLng(dr.Origin); err != nil {
		return fmt.Errorf("origin invalid: %w", err)
	}
	if err := ValidateLatLng(dr.Destination); err != nil {
		return fmt.Errorf("destination invalid: %w", err)
	}
	if len(dr.Intermediates) > 25 {
		return fmt.Errorf("intermediates cannot exceed 25 waypoints (got %d)", len(dr.Intermediates))
	}
	for i, pt := range dr.Intermediates {
		if err := ValidateLatLng(pt); err != nil {
			return fmt.Errorf("intermediate[%d] invalid: %w", i, err)
		}
	}
	return nil
}

// ValidateRouteAttributes enforces Discovery 20261101 routeAttributes constraints:
//   - Maximum 25 key-value entries.
//   - Every key and value must be a non-empty string of 1-100 Unicode code points.
//   - Keys must not start with reserved prefix "goog" (case-sensitive).
func ValidateRouteAttributes(attrs map[string]string) error {
	if len(attrs) > 25 {
		return fmt.Errorf("routeAttributes cannot exceed 25 entries (got %d)", len(attrs))
	}
	for k, v := range attrs {
		kLen := utf8.RuneCountInString(k)
		if kLen < 1 || kLen > 100 {
			return fmt.Errorf("attribute key %q must be 1-100 Unicode code points (got %d)", k, kLen)
		}
		vLen := utf8.RuneCountInString(v)
		if vLen < 1 || vLen > 100 {
			return fmt.Errorf("attribute value for key %q must be a non-empty string of 1-100 Unicode code points (got %d)", k, vLen)
		}
		if strings.HasPrefix(k, "goog") {
			return fmt.Errorf("attribute key %q cannot start with reserved prefix 'goog'", k)
		}
	}
	return nil
}

// ValidateSelectedRoute validates a SelectedRoute and optional selectedRouteId.
func ValidateSelectedRoute(routeID string, route SelectedRoute, requireDynamicRoute bool) error {
	if err := ValidateSelectedRouteID(routeID); err != nil {
		return err
	}
	if err := ValidateDisplayName(route.DisplayName); err != nil {
		return err
	}
	if requireDynamicRoute || route.DynamicRoute != nil {
		if err := ValidateDynamicRoute(route.DynamicRoute); err != nil {
			return err
		}
	}
	if err := ValidateRouteAttributes(route.RouteAttributes); err != nil {
		return err
	}
	return nil
}

// ClientOptions configures a RoadsSelectionClient instance.
type ClientOptions struct {
	ProjectID      string
	QuotaProjectID string
	BaseURL        string
	AccessToken    string
	TokenProvider  func(ctx context.Context) (string, error)
	HTTPClient     *http.Client
}

// RoadsSelectionClient is a strongly typed REST client for the Roads Selection API v1.
type RoadsSelectionClient struct {
	projectID      string
	quotaProjectID string
	baseURL        string
	accessToken    string
	tokenProvider  func(ctx context.Context) (string, error)
	httpClient     *http.Client
}

// NewRoadsSelectionClient constructs a new RoadsSelectionClient with defaults.
func NewRoadsSelectionClient(opts ClientOptions) (*RoadsSelectionClient, error) {
	projectID := strings.TrimSpace(opts.ProjectID)
	if projectID == "" {
		return nil, errors.New("ProjectID is required")
	}
	quotaProjectID := strings.TrimSpace(opts.QuotaProjectID)
	if quotaProjectID == "" {
		quotaProjectID = projectID
	}
	baseURL := strings.TrimSpace(opts.BaseURL)
	if baseURL == "" {
		baseURL = strings.TrimSpace(os.Getenv("ROADSSELECTION_BASE_URL"))
	}
	if baseURL == "" {
		baseURL = DefaultBaseURL
	}
	baseURL = strings.TrimRight(baseURL, "/")

	httpClient := opts.HTTPClient
	if httpClient == nil {
		httpClient = &http.Client{Timeout: 60 * time.Second}
	}

	return &RoadsSelectionClient{
		projectID:      projectID,
		quotaProjectID: quotaProjectID,
		baseURL:        baseURL,
		accessToken:    opts.AccessToken,
		tokenProvider:  opts.TokenProvider,
		httpClient:     httpClient,
	}, nil
}

func (c *RoadsSelectionClient) resolveResourceName(routeIDOrName string) (string, error) {
	trimmed := strings.TrimSpace(routeIDOrName)
	if trimmed == "" {
		return "", errors.New("route ID or resource name is required")
	}
	if strings.HasPrefix(trimmed, "projects/") {
		return trimmed, nil
	}
	if err := ValidateSelectedRouteID(trimmed); err != nil {
		return "", err
	}
	return fmt.Sprintf("projects/%s/selectedRoutes/%s", c.projectID, trimmed), nil
}

func (c *RoadsSelectionClient) resolveToken(ctx context.Context) (string, error) {
	if c.accessToken != "" {
		return c.accessToken, nil
	}
	if c.tokenProvider != nil {
		return c.tokenProvider(ctx)
	}
	for _, envName := range []string{"GOOGLE_OAUTH_ACCESS_TOKEN", "ROADSSELECTION_ACCESS_TOKEN", "CLOUDSDK_AUTH_ACCESS_TOKEN"} {
		if tok := strings.TrimSpace(os.Getenv(envName)); tok != "" {
			return tok, nil
		}
	}
	cmd := exec.CommandContext(ctx, "gcloud", "auth", "application-default", "print-access-token")
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("failed to resolve OAuth token (set AccessToken, GOOGLE_OAUTH_ACCESS_TOKEN, or configure gcloud ADC): %w", err)
	}
	tok := strings.TrimSpace(string(out))
	if tok == "" {
		return "", errors.New("gcloud returned an empty access token")
	}
	return tok, nil
}

func (c *RoadsSelectionClient) doJSON(ctx context.Context, method, fullURL string, reqBody any, respOut any) error {
	tok, err := c.resolveToken(ctx)
	if err != nil {
		return err
	}

	var bodyReader io.Reader
	if reqBody != nil {
		encoded, err := json.Marshal(reqBody)
		if err != nil {
			return fmt.Errorf("failed to marshal request JSON: %w", err)
		}
		bodyReader = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, method, fullURL, bodyReader)
	if err != nil {
		return fmt.Errorf("failed to build HTTP request: %w", err)
	}
	req.Header.Set("Authorization", "Bearer "+tok)
	req.Header.Set("X-Goog-User-Project", c.quotaProjectID)
	if reqBody != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("HTTP %s %s failed: %w", method, fullURL, err)
	}
	defer resp.Body.Close()

	respBytes, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed reading response body: %w", err)
	}

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return &APIError{
			StatusCode: resp.StatusCode,
			Method:     method,
			URL:        fullURL,
			Body:       strings.TrimSpace(string(respBytes)),
		}
	}

	if respOut != nil && len(bytes.TrimSpace(respBytes)) > 0 {
		if err := json.Unmarshal(respBytes, respOut); err != nil {
			return fmt.Errorf("failed to decode response JSON: %w", err)
		}
	}
	return nil
}

// CreateSelectedRoute creates a single SelectedRoute via POST /projects/{project}/selectedRoutes.
// Pass an empty routeID ("") to let the server generate a UUID automatically.
func (c *RoadsSelectionClient) CreateSelectedRoute(ctx context.Context, routeID string, route SelectedRoute) (*SelectedRoute, error) {
	if err := ValidateSelectedRoute(routeID, route, true); err != nil {
		return nil, err
	}
	endpoint := fmt.Sprintf("%s/projects/%s/selectedRoutes", c.baseURL, url.PathEscape(c.projectID))
	if routeID != "" {
		q := url.Values{}
		q.Set("selectedRouteId", routeID)
		endpoint += "?" + q.Encode()
	}
	var out SelectedRoute
	if err := c.doJSON(ctx, http.MethodPost, endpoint, route, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// BatchCreateSelectedRoutes atomically creates up to 1,000 SelectedRoutes via POST .../selectedRoutes:batchCreate.
func (c *RoadsSelectionClient) BatchCreateSelectedRoutes(ctx context.Context, requests []CreateSelectedRouteRequest) (*BatchCreateSelectedRoutesResponse, error) {
	if len(requests) == 0 || len(requests) > 1000 {
		return nil, fmt.Errorf("BatchCreateSelectedRoutes requires 1-1000 requests (got %d)", len(requests))
	}
	expectedParent := "projects/" + c.projectID
	for i, item := range requests {
		if item.Parent != "" && item.Parent != expectedParent {
			return nil, fmt.Errorf("requests[%d].parent %q must match %q or be empty", i, item.Parent, expectedParent)
		}
		if err := ValidateSelectedRoute(item.SelectedRouteID, item.SelectedRoute, true); err != nil {
			return nil, fmt.Errorf("requests[%d] invalid: %w", i, err)
		}
	}
	endpoint := fmt.Sprintf("%s/projects/%s/selectedRoutes:batchCreate", c.baseURL, url.PathEscape(c.projectID))
	payload := BatchCreateSelectedRoutesRequest{Requests: requests}
	var out BatchCreateSelectedRoutesResponse
	if err := c.doJSON(ctx, http.MethodPost, endpoint, payload, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// GetSelectedRoute retrieves a SelectedRoute by short ID or full resource name.
func (c *RoadsSelectionClient) GetSelectedRoute(ctx context.Context, routeIDOrName string) (*SelectedRoute, error) {
	resName, err := c.resolveResourceName(routeIDOrName)
	if err != nil {
		return nil, err
	}
	endpoint := fmt.Sprintf("%s/%s", c.baseURL, resName)
	var out SelectedRoute
	if err := c.doJSON(ctx, http.MethodGet, endpoint, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// UpdateSelectedRoute modifies an existing SelectedRoute in-place via HTTP PATCH and updateMask.
func (c *RoadsSelectionClient) UpdateSelectedRoute(ctx context.Context, routeIDOrName string, route SelectedRoute, updateMask string) (*SelectedRoute, error) {
	resName, err := c.resolveResourceName(routeIDOrName)
	if err != nil {
		return nil, err
	}
	route.Name = resName
	if err := ValidateSelectedRoute("", route, false); err != nil {
		return nil, err
	}

	mask := strings.TrimSpace(updateMask)
	if mask == "" {
		var inferred []string
		if route.DisplayName != "" {
			inferred = append(inferred, "displayName")
		}
		if route.DynamicRouting != nil {
			inferred = append(inferred, "dynamicRouting")
		}
		if route.RouteAttributes != nil {
			inferred = append(inferred, "routeAttributes")
		}
		if route.DynamicRoute != nil {
			inferred = append(inferred, "dynamicRoute")
		}
		mask = strings.Join(inferred, ",")
	}

	endpoint := fmt.Sprintf("%s/%s", c.baseURL, resName)
	if mask != "" {
		q := url.Values{}
		q.Set("updateMask", mask)
		endpoint += "?" + q.Encode()
	}

	var out SelectedRoute
	if err := c.doJSON(ctx, http.MethodPatch, endpoint, route, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// BatchUpdateSelectedRoutes updates up to 1,000 SelectedRoutes in a single batch via POST .../selectedRoutes:batchUpdate.
func (c *RoadsSelectionClient) BatchUpdateSelectedRoutes(ctx context.Context, requests []UpdateSelectedRouteRequest, updateMask string) (*BatchUpdateSelectedRoutesResponse, error) {
	if len(requests) == 0 || len(requests) > 1000 {
		return nil, fmt.Errorf("BatchUpdateSelectedRoutes requires 1-1000 requests (got %d)", len(requests))
	}
	expectedPrefix := fmt.Sprintf("projects/%s/selectedRoutes/", c.projectID)
	batchMask := strings.TrimSpace(updateMask)
	for i, item := range requests {
		if !strings.HasPrefix(item.SelectedRoute.Name, expectedPrefix) || len(item.SelectedRoute.Name) <= len(expectedPrefix) {
			return nil, fmt.Errorf("requests[%d].selectedRoute.name %q must belong to project %q", i, item.SelectedRoute.Name, c.projectID)
		}
		childMask := strings.TrimSpace(item.UpdateMask)
		if batchMask != "" && childMask != "" && childMask != batchMask {
			return nil, fmt.Errorf("requests[%d] child updateMask %q must match batch updateMask %q", i, childMask, batchMask)
		}
		if err := ValidateSelectedRoute("", item.SelectedRoute, false); err != nil {
			return nil, fmt.Errorf("requests[%d] invalid: %w", i, err)
		}
	}

	endpoint := fmt.Sprintf("%s/projects/%s/selectedRoutes:batchUpdate", c.baseURL, url.PathEscape(c.projectID))
	payload := BatchUpdateSelectedRoutesRequest{
		Requests:   requests,
		UpdateMask: batchMask,
	}
	var out BatchUpdateSelectedRoutesResponse
	if err := c.doJSON(ctx, http.MethodPost, endpoint, payload, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ListSelectedRoutes fetches a single paginated page of SelectedRoutes.
// Per Discovery 20261101, pageSize == 0 defaults to 100 and values > 5000 are clamped to 5000.
func (c *RoadsSelectionClient) ListSelectedRoutes(ctx context.Context, pageSize int, pageToken string) (*ListSelectedRoutesResponse, error) {
	if pageSize < 0 {
		return nil, fmt.Errorf("pageSize cannot be negative (got %d)", pageSize)
	}
	effectiveSize := pageSize
	if effectiveSize == 0 {
		effectiveSize = 100
	} else if effectiveSize > 5000 {
		effectiveSize = 5000
	}

	q := url.Values{}
	q.Set("pageSize", strconv.Itoa(effectiveSize))
	if pageToken != "" {
		q.Set("pageToken", pageToken)
	}
	endpoint := fmt.Sprintf("%s/projects/%s/selectedRoutes?%s", c.baseURL, url.PathEscape(c.projectID), q.Encode())

	var out ListSelectedRoutesResponse
	if err := c.doJSON(ctx, http.MethodGet, endpoint, nil, &out); err != nil {
		return nil, err
	}
	return &out, nil
}

// ListAllSelectedRoutes iterates through all pages and returns the full slice of SelectedRoutes.
func (c *RoadsSelectionClient) ListAllSelectedRoutes(ctx context.Context, pageSize int) ([]SelectedRoute, error) {
	var all []SelectedRoute
	pageToken := ""
	for {
		page, err := c.ListSelectedRoutes(ctx, pageSize, pageToken)
		if err != nil {
			return nil, err
		}
		all = append(all, page.SelectedRoutes...)
		if page.NextPageToken == "" {
			break
		}
		pageToken = page.NextPageToken
	}
	return all, nil
}

// DeleteSelectedRoute deletes a single SelectedRoute by short ID or full resource name.
func (c *RoadsSelectionClient) DeleteSelectedRoute(ctx context.Context, routeIDOrName string) error {
	resName, err := c.resolveResourceName(routeIDOrName)
	if err != nil {
		return err
	}
	endpoint := fmt.Sprintf("%s/%s", c.baseURL, resName)
	return c.doJSON(ctx, http.MethodDelete, endpoint, nil, nil)
}

// BatchDeleteSelectedRoutes atomically deletes up to 1,000 SelectedRoutes via POST .../selectedRoutes:batchDelete.
func (c *RoadsSelectionClient) BatchDeleteSelectedRoutes(ctx context.Context, routeIDsOrNames []string) error {
	if len(routeIDsOrNames) == 0 || len(routeIDsOrNames) > 1000 {
		return fmt.Errorf("BatchDeleteSelectedRoutes requires 1-1000 route names (got %d)", len(routeIDsOrNames))
	}
	expectedPrefix := fmt.Sprintf("projects/%s/selectedRoutes/", c.projectID)
	names := make([]string, 0, len(routeIDsOrNames))
	for i, item := range routeIDsOrNames {
		resName, err := c.resolveResourceName(item)
		if err != nil {
			return fmt.Errorf("names[%d] invalid: %w", i, err)
		}
		if !strings.HasPrefix(resName, expectedPrefix) || len(resName) <= len(expectedPrefix) {
			return fmt.Errorf("names[%d] %q must belong to project %q", i, resName, c.projectID)
		}
		names = append(names, resName)
	}

	endpoint := fmt.Sprintf("%s/projects/%s/selectedRoutes:batchDelete", c.baseURL, url.PathEscape(c.projectID))
	payload := BatchDeleteSelectedRoutesRequest{Names: names}
	return c.doJSON(ctx, http.MethodPost, endpoint, payload, nil)
}

// WaitForRouteState polls GetSelectedRoute until targetState is reached or ctx expires.
// If the route enters STATE_INVALID (and targetState != STATE_INVALID), an error is returned immediately.
func (c *RoadsSelectionClient) WaitForRouteState(ctx context.Context, routeIDOrName string, targetState string, pollInterval time.Duration) (*SelectedRoute, error) {
	if targetState == "" {
		targetState = StateRunning
	}
	if pollInterval <= 0 {
		pollInterval = 2 * time.Second
	}
	for {
		route, err := c.GetSelectedRoute(ctx, routeIDOrName)
		if err != nil {
			return nil, err
		}
		if route.State == targetState {
			return route, nil
		}
		if targetState != StateInvalid && route.State == StateInvalid {
			valErr := route.ValidationError
			if valErr == "" {
				valErr = ValidationErrorUnspecified
			}
			return route, fmt.Errorf("route %q entered %s (validationError=%s)", route.Name, StateInvalid, valErr)
		}

		timer := time.NewTimer(pollInterval)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil, ctx.Err()
		case <-timer.C:
		}
	}
}
