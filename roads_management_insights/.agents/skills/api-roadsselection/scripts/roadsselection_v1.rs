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

//! Roads Selection API v1 Reference Client for Rust (`std`-only, zero external crates).
//!
//! Grounded in official Discovery Document `roads_selection_v1_20261104.json`
//! (`id: roads:selection_v1`, revision `20261104`,
//! `https://roads.googleapis.com/$discovery/rest?version=selection_v1`,
//! base endpoint `https://roads.googleapis.com/selection/v1`).
//!
//! Compiles and runs offline with zero external dependencies:
//! `rustc --edition 2021 --test scripts/roadsselection_v1.rs -o /tmp/rs_test && /tmp/rs_test`
//!
//! Supported RPC Methods:
//!   1. `create_selected_route` (`POST /projects/{project}/selectedRoutes`)
//!   2. `batch_create_selected_routes` (`POST /projects/{project}/selectedRoutes:batchCreate`)
//!   3. `get_selected_route` (`GET /projects/{project}/selectedRoutes/{id}`)
//!   4. `update_selected_route` (`PATCH /projects/{project}/selectedRoutes/{id}?updateMask=...`)
//!   5. `batch_update_selected_routes` (`POST /projects/{project}/selectedRoutes:batchUpdate`)
//!   6. `list_selected_routes` / `list_all_selected_routes` (`GET /projects/{project}/selectedRoutes`)
//!   7. `delete_selected_route` (`DELETE /projects/{project}/selectedRoutes/{id}`)
//!   8. `batch_delete_selected_routes` (`POST /projects/{project}/selectedRoutes:batchDelete`)

#![allow(dead_code)]

use std::collections::BTreeMap;
use std::env;
use std::error::Error;
use std::fmt;
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant};

/// Canonical Roads Selection API v1 REST base URL.
pub const DEFAULT_BASE_URL: &str = "https://roads.googleapis.com/selection/v1";

/// Lifecycle `State` enum values (`SelectedRoute.state`).
pub const STATE_UNSPECIFIED: &str = "STATE_UNSPECIFIED";
pub const STATE_SCHEDULING: &str = "STATE_SCHEDULING";
pub const STATE_RUNNING: &str = "STATE_RUNNING";
pub const STATE_DELETING: &str = "STATE_DELETING";
pub const STATE_VALIDATING: &str = "STATE_VALIDATING";
pub const STATE_INVALID: &str = "STATE_INVALID";

/// `ValidationError` enum values (`SelectedRoute.validationError`).
pub const VALIDATION_ERROR_UNSPECIFIED: &str = "VALIDATION_ERROR_UNSPECIFIED";
pub const VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION: &str =
    "VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION";
pub const VALIDATION_ERROR_LOW_ROAD_USAGE: &str = "VALIDATION_ERROR_LOW_ROAD_USAGE";

/// Error type returned by `RoadsSelectionClient` and validation functions.
#[derive(Debug, Clone, PartialEq)]
pub enum RoadsSelectionError {
    Validation(String),
    Auth(String),
    Transport(String),
    Parse(String),
    Timeout(String),
    Http {
        status: u16,
        method: String,
        url: String,
        body: String,
    },
}

impl fmt::Display for RoadsSelectionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RoadsSelectionError::Validation(msg) => write!(f, "validation error: {}", msg),
            RoadsSelectionError::Auth(msg) => write!(f, "auth error: {}", msg),
            RoadsSelectionError::Transport(msg) => write!(f, "transport error: {}", msg),
            RoadsSelectionError::Parse(msg) => write!(f, "JSON parse error: {}", msg),
            RoadsSelectionError::Timeout(msg) => write!(f, "timeout error: {}", msg),
            RoadsSelectionError::Http {
                status,
                method,
                url,
                body,
            } => write!(
                f,
                "roadsselection {} {} failed [{}]: {}",
                method, url, status, body
            ),
        }
    }
}

impl Error for RoadsSelectionError {}

/// WGS84 geographic coordinates in decimal degrees.
#[derive(Debug, Clone, PartialEq)]
pub struct LatLng {
    pub latitude: f64,
    pub longitude: f64,
}

impl LatLng {
    pub fn new(latitude: f64, longitude: f64) -> Self {
        Self {
            latitude,
            longitude,
        }
    }
}

/// Dynamic route geometry (`origin`, `destination`, and up to 25 `intermediates`).
#[derive(Debug, Clone, PartialEq)]
pub struct DynamicRoute {
    pub origin: LatLng,
    pub destination: LatLng,
    pub intermediates: Vec<LatLng>,
}

impl DynamicRoute {
    pub fn new(origin: LatLng, destination: LatLng) -> Self {
        Self {
            origin,
            destination,
            intermediates: Vec::new(),
        }
    }

    pub fn with_intermediates(mut self, intermediates: Vec<LatLng>) -> Self {
        self.intermediates = intermediates;
        self
    }
}

/// Monitored corridor resource in the Roads Selection API v1 (`SelectedRoute`).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct SelectedRoute {
    pub name: Option<String>,
    pub display_name: Option<String>,
    pub dynamic_route: Option<DynamicRoute>,
    pub dynamic_routing: Option<bool>,
    pub route_attributes: BTreeMap<String, String>,
    pub create_time: Option<String>,
    pub state: Option<String>,
    pub validation_error: Option<String>,
}

/// Child item for `batch_create_selected_routes` (`CreateSelectedRouteRequest`).
#[derive(Debug, Clone, PartialEq)]
pub struct CreateRouteInput {
    pub parent: Option<String>,
    pub selected_route_id: Option<String>,
    pub selected_route: SelectedRoute,
}

/// Child item for `batch_update_selected_routes` (`UpdateSelectedRouteRequest`).
#[derive(Debug, Clone, PartialEq)]
pub struct UpdateRouteInput {
    pub selected_route: SelectedRoute,
    pub update_mask: Option<String>,
}

/// Paginated response returned by `list_selected_routes` (`ListSelectedRoutesResponse`).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct ListSelectedRoutesResponse {
    pub selected_routes: Vec<SelectedRoute>,
    pub next_page_token: Option<String>,
}

// =============================================================================
// Discovery 20261104 Validators
// =============================================================================

/// Validates `selectedRouteId`:
/// - `None` or `Some("")` is valid (server auto-generates a UUID on creation).
/// - Otherwise 4..=63 ASCII characters matching `[a-zA-Z0-9_-]`.
pub fn validate_selected_route_id(route_id: Option<&str>) -> Result<(), RoadsSelectionError> {
    let id = match route_id {
        None | Some("") => return Ok(()),
        Some(v) => v,
    };
    let len = id.len();
    if !(4..=63).contains(&len) {
        return Err(RoadsSelectionError::Validation(format!(
            "selectedRouteId '{}' must be 4-63 characters (got {})",
            id, len
        )));
    }
    if !id
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err(RoadsSelectionError::Validation(format!(
            "selectedRouteId '{}' contains invalid characters; valid characters are 'a-z', 'A-Z', '0-9', '-', or '_'",
            id
        )));
    }
    Ok(())
}

/// Validates `displayName` (`<= 100` Unicode code points via `.chars().count()`).
pub fn validate_display_name(display_name: &str) -> Result<(), RoadsSelectionError> {
    let count = display_name.chars().count();
    if count > 100 {
        return Err(RoadsSelectionError::Validation(format!(
            "displayName cannot exceed 100 Unicode code points (got {})",
            count
        )));
    }
    Ok(())
}

/// Validates WGS84 latitude `[-90, 90]` and longitude `[-180, 180]`.
pub fn validate_lat_lng(coord: &LatLng) -> Result<(), RoadsSelectionError> {
    if !(-90.0..=90.0).contains(&coord.latitude) {
        return Err(RoadsSelectionError::Validation(format!(
            "latitude {} out of [-90, 90] bounds",
            coord.latitude
        )));
    }
    if !(-180.0..=180.0).contains(&coord.longitude) {
        return Err(RoadsSelectionError::Validation(format!(
            "longitude {} out of [-180, 180] bounds",
            coord.longitude
        )));
    }
    Ok(())
}

/// Validates `DynamicRoute` (`origin`, `destination`, and `<= 25` `intermediates`).
pub fn validate_dynamic_route(dr: &DynamicRoute) -> Result<(), RoadsSelectionError> {
    validate_lat_lng(&dr.origin)?;
    validate_lat_lng(&dr.destination)?;
    if dr.intermediates.len() > 25 {
        return Err(RoadsSelectionError::Validation(format!(
            "intermediates cannot exceed 25 waypoints (got {})",
            dr.intermediates.len()
        )));
    }
    for pt in &dr.intermediates {
        validate_lat_lng(pt)?;
    }
    Ok(())
}

/// Validates `routeAttributes` per Discovery 20261104:
/// - Maximum 25 key-value entries.
/// - Keys and values must be non-empty strings of `1..=100` Unicode code points.
/// - Keys cannot start with reserved prefix `"goog"` (case-sensitive).
pub fn validate_route_attributes(
    attrs: &BTreeMap<String, String>,
) -> Result<(), RoadsSelectionError> {
    if attrs.len() > 25 {
        return Err(RoadsSelectionError::Validation(format!(
            "routeAttributes cannot exceed 25 entries (got {})",
            attrs.len()
        )));
    }
    for (k, v) in attrs {
        let k_len = k.chars().count();
        if !(1..=100).contains(&k_len) {
            return Err(RoadsSelectionError::Validation(format!(
                "attribute key '{}' must be 1-100 Unicode code points (got {})",
                k, k_len
            )));
        }
        let v_len = v.chars().count();
        if !(1..=100).contains(&v_len) {
            return Err(RoadsSelectionError::Validation(format!(
                "attribute value for key '{}' must be a non-empty string of 1-100 Unicode code points (got {})",
                k, v_len
            )));
        }
        if k.starts_with("goog") {
            return Err(RoadsSelectionError::Validation(format!(
                "attribute key '{}' cannot start with reserved prefix 'goog'",
                k
            )));
        }
    }
    Ok(())
}

/// Validates a `SelectedRoute` and optional `selectedRouteId`.
pub fn validate_selected_route(
    route_id: Option<&str>,
    route: &SelectedRoute,
    require_dynamic_route: bool,
) -> Result<(), RoadsSelectionError> {
    validate_selected_route_id(route_id)?;
    if let Some(dn) = &route.display_name {
        validate_display_name(dn)?;
    }
    match &route.dynamic_route {
        Some(dr) => validate_dynamic_route(dr)?,
        None if require_dynamic_route => {
            return Err(RoadsSelectionError::Validation(
                "dynamicRoute is required".to_string(),
            ));
        }
        None => {}
    }
    validate_route_attributes(&route.route_attributes)?;
    Ok(())
}

// =============================================================================
// Minimal RFC-8259 JSON Serializer & Recursive-Descent Parser (std-only)
// =============================================================================

fn json_escape_str(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn url_encode_component(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        if b.is_ascii_alphanumeric() || b == b'-' || b == b'_' || b == b'.' || b == b'~' {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{:02X}", b));
        }
    }
    out
}

impl LatLng {
    pub fn to_json(&self) -> String {
        format!(
            "{{\"latitude\":{},\"longitude\":{}}}",
            self.latitude, self.longitude
        )
    }
}

impl DynamicRoute {
    pub fn to_json(&self) -> String {
        let mut fields = vec![
            format!("\"origin\":{}", self.origin.to_json()),
            format!("\"destination\":{}", self.destination.to_json()),
        ];
        if !self.intermediates.is_empty() {
            let pts: Vec<String> = self.intermediates.iter().map(LatLng::to_json).collect();
            fields.push(format!("\"intermediates\":[{}]", pts.join(",")));
        }
        format!("{{{}}}", fields.join(","))
    }
}

impl SelectedRoute {
    pub fn to_json(&self) -> String {
        let mut fields: Vec<String> = Vec::new();
        if let Some(name) = &self.name {
            fields.push(format!("\"name\":{}", json_escape_str(name)));
        }
        if let Some(dn) = &self.display_name {
            fields.push(format!("\"displayName\":{}", json_escape_str(dn)));
        }
        if let Some(dr) = &self.dynamic_route {
            fields.push(format!("\"dynamicRoute\":{}", dr.to_json()));
        }
        if let Some(dyn_routing) = self.dynamic_routing {
            fields.push(format!(
                "\"dynamicRouting\":{}",
                if dyn_routing { "true" } else { "false" }
            ));
        }
        if !self.route_attributes.is_empty() {
            let entries: Vec<String> = self
                .route_attributes
                .iter()
                .map(|(k, v)| format!("{}:{}", json_escape_str(k), json_escape_str(v)))
                .collect();
            fields.push(format!("\"routeAttributes\":{{{}}}", entries.join(",")));
        }
        format!("{{{}}}", fields.join(","))
    }
}

#[derive(Debug, Clone, PartialEq)]
enum JsonValue {
    Null,
    Bool(bool),
    Number(f64),
    Str(String),
    Array(Vec<JsonValue>),
    Object(BTreeMap<String, JsonValue>),
}

struct JsonParser<'a> {
    chars: Vec<char>,
    pos: usize,
    _marker: &'a (),
}

impl<'a> JsonParser<'a> {
    fn new(input: &'a str) -> Self {
        Self {
            chars: input.chars().collect(),
            pos: 0,
            _marker: &(),
        }
    }

    fn skip_ws(&mut self) {
        while self.pos < self.chars.len() && self.chars[self.pos].is_ascii_whitespace() {
            self.pos += 1;
        }
    }

    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }

    fn next_char(&mut self) -> Option<char> {
        let ch = self.peek()?;
        self.pos += 1;
        Some(ch)
    }

    fn parse_value(&mut self) -> Result<JsonValue, RoadsSelectionError> {
        self.skip_ws();
        match self.peek() {
            Some('"') => self.parse_string().map(JsonValue::Str),
            Some('{') => self.parse_object(),
            Some('[') => self.parse_array(),
            Some('t') => self.expect_literal("true", JsonValue::Bool(true)),
            Some('f') => self.expect_literal("false", JsonValue::Bool(false)),
            Some('n') => self.expect_literal("null", JsonValue::Null),
            Some(c) if c == '-' || c.is_ascii_digit() => self.parse_number(),
            other => Err(RoadsSelectionError::Parse(format!(
                "unexpected token {:?} at char {}",
                other, self.pos
            ))),
        }
    }

    fn expect_literal(
        &mut self,
        lit: &str,
        val: JsonValue,
    ) -> Result<JsonValue, RoadsSelectionError> {
        for expected in lit.chars() {
            if self.next_char() != Some(expected) {
                return Err(RoadsSelectionError::Parse(format!(
                    "expected literal '{}'",
                    lit
                )));
            }
        }
        Ok(val)
    }

    fn parse_string(&mut self) -> Result<String, RoadsSelectionError> {
        if self.next_char() != Some('"') {
            return Err(RoadsSelectionError::Parse("expected '\"'".to_string()));
        }
        let mut out = String::new();
        while let Some(ch) = self.next_char() {
            match ch {
                '"' => return Ok(out),
                '\\' => {
                    let esc = self.next_char().ok_or_else(|| {
                        RoadsSelectionError::Parse("unterminated escape sequence".to_string())
                    })?;
                    match esc {
                        '"' => out.push('"'),
                        '\\' => out.push('\\'),
                        '/' => out.push('/'),
                        'b' => out.push('\x08'),
                        'f' => out.push('\x0c'),
                        'n' => out.push('\n'),
                        'r' => out.push('\r'),
                        't' => out.push('\t'),
                        'u' => {
                            let mut hex = String::with_capacity(4);
                            for _ in 0..4 {
                                let hc = self.next_char().ok_or_else(|| {
                                    RoadsSelectionError::Parse("incomplete \\u escape".to_string())
                                })?;
                                hex.push(hc);
                            }
                            let code = u32::from_str_radix(&hex, 16).map_err(|_| {
                                RoadsSelectionError::Parse(format!("invalid \\u{}", hex))
                            })?;
                            if let Some(decoded) = char::from_u32(code) {
                                out.push(decoded);
                            }
                        }
                        other => out.push(other),
                    }
                }
                c => out.push(c),
            }
        }
        Err(RoadsSelectionError::Parse(
            "unterminated JSON string".to_string(),
        ))
    }

    fn parse_number(&mut self) -> Result<JsonValue, RoadsSelectionError> {
        let start = self.pos;
        while let Some(c) = self.peek() {
            if c.is_ascii_digit() || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E' {
                self.pos += 1;
            } else {
                break;
            }
        }
        let s: String = self.chars[start..self.pos].iter().collect();
        let num = s
            .parse::<f64>()
            .map_err(|e| RoadsSelectionError::Parse(format!("invalid number '{}': {}", s, e)))?;
        Ok(JsonValue::Number(num))
    }

    fn parse_array(&mut self) -> Result<JsonValue, RoadsSelectionError> {
        self.next_char(); // '['
        let mut items = Vec::new();
        self.skip_ws();
        if self.peek() == Some(']') {
            self.next_char();
            return Ok(JsonValue::Array(items));
        }
        loop {
            items.push(self.parse_value()?);
            self.skip_ws();
            match self.next_char() {
                Some(',') => continue,
                Some(']') => break,
                other => {
                    return Err(RoadsSelectionError::Parse(format!(
                        "expected ',' or ']' in array, got {:?}",
                        other
                    )))
                }
            }
        }
        Ok(JsonValue::Array(items))
    }

    fn parse_object(&mut self) -> Result<JsonValue, RoadsSelectionError> {
        self.next_char(); // '{'
        let mut map = BTreeMap::new();
        self.skip_ws();
        if self.peek() == Some('}') {
            self.next_char();
            return Ok(JsonValue::Object(map));
        }
        loop {
            self.skip_ws();
            let key = self.parse_string()?;
            self.skip_ws();
            if self.next_char() != Some(':') {
                return Err(RoadsSelectionError::Parse(
                    "expected ':' after object key".to_string(),
                ));
            }
            let val = self.parse_value()?;
            map.insert(key, val);
            self.skip_ws();
            match self.next_char() {
                Some(',') => continue,
                Some('}') => break,
                other => {
                    return Err(RoadsSelectionError::Parse(format!(
                        "expected ',' or '}}' in object, got {:?}",
                        other
                    )))
                }
            }
        }
        Ok(JsonValue::Object(map))
    }
}

fn parse_json(input: &str) -> Result<JsonValue, RoadsSelectionError> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return Ok(JsonValue::Object(BTreeMap::new()));
    }
    let mut parser = JsonParser::new(trimmed);
    let val = parser.parse_value()?;
    parser.skip_ws();
    if parser.pos != parser.chars.len() {
        return Err(RoadsSelectionError::Parse(
            "trailing characters after JSON value".to_string(),
        ));
    }
    Ok(val)
}

fn decode_lat_lng(val: &JsonValue) -> Result<LatLng, RoadsSelectionError> {
    let obj = match val {
        JsonValue::Object(m) => m,
        _ => return Err(RoadsSelectionError::Parse("expected LatLng object".to_string())),
    };
    let lat = match obj.get("latitude") {
        Some(JsonValue::Number(n)) => *n,
        _ => 0.0,
    };
    let lng = match obj.get("longitude") {
        Some(JsonValue::Number(n)) => *n,
        _ => 0.0,
    };
    Ok(LatLng::new(lat, lng))
}

fn decode_selected_route(val: &JsonValue) -> Result<SelectedRoute, RoadsSelectionError> {
    let obj = match val {
        JsonValue::Object(m) => m,
        _ => {
            return Err(RoadsSelectionError::Parse(
                "expected SelectedRoute JSON object".to_string(),
            ))
        }
    };

    let get_str = |k1: &str, k2: &str| -> Option<String> {
        match obj.get(k1).or_else(|| obj.get(k2)) {
            Some(JsonValue::Str(s)) => Some(s.clone()),
            _ => None,
        }
    };

    let dynamic_route = match obj.get("dynamicRoute").or_else(|| obj.get("dynamic_route")) {
        Some(JsonValue::Object(dr_map)) => {
            let origin = dr_map
                .get("origin")
                .map(decode_lat_lng)
                .transpose()?
                .unwrap_or_else(|| LatLng::new(0.0, 0.0));
            let destination = dr_map
                .get("destination")
                .map(decode_lat_lng)
                .transpose()?
                .unwrap_or_else(|| LatLng::new(0.0, 0.0));
            let mut intermediates = Vec::new();
            if let Some(JsonValue::Array(arr)) = dr_map.get("intermediates") {
                for item in arr {
                    intermediates.push(decode_lat_lng(item)?);
                }
            }
            Some(DynamicRoute {
                origin,
                destination,
                intermediates,
            })
        }
        _ => None,
    };

    let dynamic_routing = match obj
        .get("dynamicRouting")
        .or_else(|| obj.get("dynamic_routing"))
    {
        Some(JsonValue::Bool(b)) => Some(*b),
        _ => None,
    };

    let mut route_attributes = BTreeMap::new();
    if let Some(JsonValue::Object(attrs)) = obj
        .get("routeAttributes")
        .or_else(|| obj.get("route_attributes"))
    {
        for (k, v) in attrs {
            if let JsonValue::Str(s) = v {
                route_attributes.insert(k.clone(), s.clone());
            }
        }
    }

    Ok(SelectedRoute {
        name: get_str("name", "name"),
        display_name: get_str("displayName", "display_name"),
        dynamic_route,
        dynamic_routing,
        route_attributes,
        create_time: get_str("createTime", "create_time"),
        state: get_str("state", "state"),
        validation_error: get_str("validationError", "validation_error"),
    })
}

// =============================================================================
// Pluggable HTTP Transport & RoadsSelectionClient
// =============================================================================

/// Outbound HTTP request passed to an `HttpTransport`.
#[derive(Debug, Clone)]
pub struct HttpRequest {
    pub method: String,
    pub url: String,
    pub headers: Vec<(String, String)>,
    pub body: Option<String>,
}

/// Raw HTTP response returned by an `HttpTransport`.
#[derive(Debug, Clone)]
pub struct HttpResponse {
    pub status: u16,
    pub body: String,
}

/// Pluggable HTTP transport trait enabling zero-crate execution and hermetic mocking.
pub trait HttpTransport {
    fn send(&self, req: &HttpRequest) -> Result<HttpResponse, RoadsSelectionError>;
}

/// Default `std::process::Command` (`curl`) HTTP transport requiring zero external Rust crates.
#[derive(Debug, Clone, Default)]
pub struct CommandCurlTransport;

impl HttpTransport for CommandCurlTransport {
    fn send(&self, req: &HttpRequest) -> Result<HttpResponse, RoadsSelectionError> {
        let mut cmd = Command::new("curl");
        cmd.arg("-sS")
            .arg("-X")
            .arg(&req.method)
            .arg("-w")
            .arg("\n%{http_code}");

        for (k, v) in &req.headers {
            cmd.arg("-H").arg(format!("{}: {}", k, v));
        }
        if let Some(body) = &req.body {
            cmd.arg("--data-raw").arg(body);
        }
        cmd.arg(&req.url);

        let output = cmd.output().map_err(|e| {
            RoadsSelectionError::Transport(format!("failed to invoke curl: {}", e))
        })?;
        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
            return Err(RoadsSelectionError::Transport(format!(
                "curl transport error: {}",
                stderr
            )));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let (body_part, status_part) = stdout.rsplit_once('\n').ok_or_else(|| {
            RoadsSelectionError::Transport("missing HTTP status trailer from curl".to_string())
        })?;
        let status = status_part.trim().parse::<u16>().map_err(|e| {
            RoadsSelectionError::Transport(format!("invalid HTTP status '{}': {}", status_part, e))
        })?;

        Ok(HttpResponse {
            status,
            body: body_part.to_string(),
        })
    }
}

/// Reference Rust client for the Google Maps Platform Roads Selection API v1.
pub struct RoadsSelectionClient<T: HttpTransport = CommandCurlTransport> {
    project_id: String,
    quota_project_id: String,
    base_url: String,
    access_token: Option<String>,
    transport: T,
}

impl RoadsSelectionClient<CommandCurlTransport> {
    /// Creates a new `RoadsSelectionClient` using the default `CommandCurlTransport`.
    pub fn new(project_id: impl Into<String>) -> Result<Self, RoadsSelectionError> {
        let pid = project_id.into();
        let base_url = env::var("ROADSSELECTION_BASE_URL")
            .unwrap_or_else(|_| DEFAULT_BASE_URL.to_string());
        Self::with_transport(pid.clone(), pid, base_url, None, CommandCurlTransport)
    }
}

impl<T: HttpTransport> RoadsSelectionClient<T> {
    /// Creates a `RoadsSelectionClient` with custom quota project, base URL, token, and transport.
    pub fn with_transport(
        project_id: impl Into<String>,
        quota_project_id: impl Into<String>,
        base_url: impl Into<String>,
        access_token: Option<String>,
        transport: T,
    ) -> Result<Self, RoadsSelectionError> {
        let pid = project_id.into().trim().to_string();
        if pid.is_empty() {
            return Err(RoadsSelectionError::Validation(
                "project_id cannot be empty".to_string(),
            ));
        }
        let qpid_raw = quota_project_id.into().trim().to_string();
        let qpid = if qpid_raw.is_empty() {
            pid.clone()
        } else {
            qpid_raw
        };
        let base_raw = base_url.into().trim().trim_end_matches('/').to_string();
        let base = if base_raw.is_empty() {
            DEFAULT_BASE_URL.to_string()
        } else {
            base_raw
        };

        Ok(Self {
            project_id: pid,
            quota_project_id: qpid,
            base_url: base,
            access_token,
            transport,
        })
    }

    fn resolve_token(&self) -> Result<String, RoadsSelectionError> {
        if let Some(tok) = &self.access_token {
            if !tok.trim().is_empty() {
                return Ok(tok.trim().to_string());
            }
        }
        for key in [
            "GOOGLE_OAUTH_ACCESS_TOKEN",
            "ROADSSELECTION_ACCESS_TOKEN",
            "CLOUDSDK_AUTH_ACCESS_TOKEN",
        ] {
            if let Ok(val) = env::var(key) {
                if !val.trim().is_empty() {
                    return Ok(val.trim().to_string());
                }
            }
        }
        let out = Command::new("gcloud")
            .args(["auth", "application-default", "print-access-token"])
            .output()
            .map_err(|e| {
                RoadsSelectionError::Auth(format!(
                    "failed to execute gcloud ADC token helper: {}",
                    e
                ))
            })?;
        if !out.status.success() {
            return Err(RoadsSelectionError::Auth(
                "gcloud auth application-default print-access-token failed".to_string(),
            ));
        }
        let tok = String::from_utf8_lossy(&out.stdout).trim().to_string();
        if tok.is_empty() {
            return Err(RoadsSelectionError::Auth(
                "empty OAuth access token".to_string(),
            ));
        }
        Ok(tok)
    }

    fn resolve_resource_name(&self, route_id_or_name: &str) -> Result<String, RoadsSelectionError> {
        let trimmed = route_id_or_name.trim();
        if trimmed.is_empty() {
            return Err(RoadsSelectionError::Validation(
                "route_id_or_name cannot be empty".to_string(),
            ));
        }
        if trimmed.starts_with("projects/") {
            return Ok(trimmed.to_string());
        }
        validate_selected_route_id(Some(trimmed))?;
        Ok(format!(
            "projects/{}/selectedRoutes/{}",
            self.project_id, trimmed
        ))
    }

    fn dispatch(
        &self,
        method: &str,
        url: String,
        body: Option<String>,
    ) -> Result<JsonValue, RoadsSelectionError> {
        let token = self.resolve_token()?;
        let mut headers = vec![
            ("Authorization".to_string(), format!("Bearer {}", token)),
            (
                "X-Goog-User-Project".to_string(),
                self.quota_project_id.clone(),
            ),
        ];
        if body.is_some() {
            headers.push(("Content-Type".to_string(), "application/json".to_string()));
        }
        let req = HttpRequest {
            method: method.to_string(),
            url: url.clone(),
            headers,
            body,
        };
        let resp = self.transport.send(&req)?;
        if !(200..300).contains(&resp.status) {
            return Err(RoadsSelectionError::Http {
                status: resp.status,
                method: method.to_string(),
                url,
                body: resp.body.trim().to_string(),
            });
        }
        parse_json(&resp.body)
    }

    /// 1. `CreateSelectedRoute`: `POST /projects/{project}/selectedRoutes`.
    /// Pass `None` or `Some("")` for `selected_route_id` to auto-generate a server UUID.
    pub fn create_selected_route(
        &self,
        selected_route_id: Option<&str>,
        route: &SelectedRoute,
    ) -> Result<SelectedRoute, RoadsSelectionError> {
        validate_selected_route(selected_route_id, route, true)?;
        let mut url = format!(
            "{}/projects/{}/selectedRoutes",
            self.base_url,
            url_encode_component(&self.project_id)
        );
        if let Some(id) = selected_route_id {
            if !id.is_empty() {
                url.push_str(&format!("?selectedRouteId={}", url_encode_component(id)));
            }
        }
        let val = self.dispatch("POST", url, Some(route.to_json()))?;
        decode_selected_route(&val)
    }

    /// 2. `BatchCreateSelectedRoutes`: `POST /projects/{project}/selectedRoutes:batchCreate`.
    /// Omits top-level `parent` from the JSON body per Discovery `20261104`.
    pub fn batch_create_selected_routes(
        &self,
        requests: &[CreateRouteInput],
    ) -> Result<Vec<SelectedRoute>, RoadsSelectionError> {
        if requests.is_empty() || requests.len() > 1000 {
            return Err(RoadsSelectionError::Validation(format!(
                "BatchCreateSelectedRoutes requires 1-1000 requests (got {})",
                requests.len()
            )));
        }
        let expected_parent = format!("projects/{}", self.project_id);
        let mut serialized_items = Vec::with_capacity(requests.len());

        for (idx, item) in requests.iter().enumerate() {
            if let Some(parent) = &item.parent {
                if !parent.is_empty() && parent != &expected_parent {
                    return Err(RoadsSelectionError::Validation(format!(
                        "requests[{}].parent '{}' must match '{}' or be omitted",
                        idx, parent, expected_parent
                    )));
                }
            }
            validate_selected_route(
                item.selected_route_id.as_deref(),
                &item.selected_route,
                true,
            )?;

            let mut item_fields = Vec::new();
            if let Some(parent) = &item.parent {
                if !parent.is_empty() {
                    item_fields.push(format!("\"parent\":{}", json_escape_str(parent)));
                }
            }
            if let Some(rid) = &item.selected_route_id {
                if !rid.is_empty() {
                    item_fields.push(format!("\"selectedRouteId\":{}", json_escape_str(rid)));
                }
            }
            item_fields.push(format!("\"selectedRoute\":{}", item.selected_route.to_json()));
            serialized_items.push(format!("{{{}}}", item_fields.join(",")));
        }

        let body = format!("{{\"requests\":[{}]}}", serialized_items.join(","));
        let url = format!(
            "{}/projects/{}/selectedRoutes:batchCreate",
            self.base_url,
            url_encode_component(&self.project_id)
        );
        let val = self.dispatch("POST", url, Some(body))?;
        Self::extract_routes_array(&val)
    }

    /// 3. `GetSelectedRoute`: `GET /projects/{project}/selectedRoutes/{id}`.
    pub fn get_selected_route(
        &self,
        route_id_or_name: &str,
    ) -> Result<SelectedRoute, RoadsSelectionError> {
        let name = self.resolve_resource_name(route_id_or_name)?;
        let url = format!("{}/{}", self.base_url, name);
        let val = self.dispatch("GET", url, None)?;
        decode_selected_route(&val)
    }

    /// 4. `UpdateSelectedRoute`: `PATCH /projects/{project}/selectedRoutes/{id}?updateMask=...`.
    pub fn update_selected_route(
        &self,
        route_id_or_name: &str,
        route: &SelectedRoute,
        update_mask: Option<&str>,
    ) -> Result<SelectedRoute, RoadsSelectionError> {
        let name = self.resolve_resource_name(route_id_or_name)?;
        let mut patched = route.clone();
        patched.name = Some(name.clone());
        validate_selected_route(None, &patched, false)?;

        let mask = match update_mask.map(str::trim).filter(|m| !m.is_empty()) {
            Some(m) => m.to_string(),
            None => {
                let mut inferred = Vec::new();
                if patched.display_name.is_some() {
                    inferred.push("displayName");
                }
                if patched.dynamic_routing.is_some() {
                    inferred.push("dynamicRouting");
                }
                if !patched.route_attributes.is_empty() {
                    inferred.push("routeAttributes");
                }
                if patched.dynamic_route.is_some() {
                    inferred.push("dynamicRoute");
                }
                inferred.join(",")
            }
        };

        let mut url = format!("{}/{}", self.base_url, name);
        if !mask.is_empty() {
            url.push_str(&format!("?updateMask={}", url_encode_component(&mask)));
        }
        let val = self.dispatch("PATCH", url, Some(patched.to_json()))?;
        decode_selected_route(&val)
    }

    /// 5. `BatchUpdateSelectedRoutes`: `POST /projects/{project}/selectedRoutes:batchUpdate`.
    /// Enforces child vs batch `updateMask` consistency and omits top-level `parent`.
    pub fn batch_update_selected_routes(
        &self,
        requests: &[UpdateRouteInput],
        update_mask: Option<&str>,
    ) -> Result<Vec<SelectedRoute>, RoadsSelectionError> {
        if requests.is_empty() || requests.len() > 1000 {
            return Err(RoadsSelectionError::Validation(format!(
                "BatchUpdateSelectedRoutes requires 1-1000 requests (got {})",
                requests.len()
            )));
        }
        let expected_prefix = format!("projects/{}/selectedRoutes/", self.project_id);
        let batch_mask = update_mask.map(str::trim).unwrap_or("");
        let mut serialized_items = Vec::with_capacity(requests.len());

        for (idx, item) in requests.iter().enumerate() {
            let route_name = item.selected_route.name.as_deref().unwrap_or("");
            if !route_name.starts_with(&expected_prefix) || route_name.len() <= expected_prefix.len()
            {
                return Err(RoadsSelectionError::Validation(format!(
                    "requests[{}].selectedRoute.name '{}' must belong to project '{}'",
                    idx, route_name, self.project_id
                )));
            }
            let child_mask = item.update_mask.as_deref().map(str::trim).unwrap_or("");
            if !batch_mask.is_empty() && !child_mask.is_empty() && child_mask != batch_mask {
                return Err(RoadsSelectionError::Validation(format!(
                    "requests[{}] child updateMask '{}' must match batch updateMask '{}'",
                    idx, child_mask, batch_mask
                )));
            }
            validate_selected_route(None, &item.selected_route, false)?;

            let mut fields = vec![format!(
                "\"selectedRoute\":{}",
                item.selected_route.to_json()
            )];
            if !child_mask.is_empty() {
                fields.push(format!("\"updateMask\":{}", json_escape_str(child_mask)));
            }
            serialized_items.push(format!("{{{}}}", fields.join(",")));
        }

        let body = if batch_mask.is_empty() {
            format!("{{\"requests\":[{}]}}", serialized_items.join(","))
        } else {
            format!(
                "{{\"requests\":[{}],\"updateMask\":{}}}",
                serialized_items.join(","),
                json_escape_str(batch_mask)
            )
        };

        let url = format!(
            "{}/projects/{}/selectedRoutes:batchUpdate",
            self.base_url,
            url_encode_component(&self.project_id)
        );
        let val = self.dispatch("POST", url, Some(body))?;
        Self::extract_routes_array(&val)
    }

    /// 6. `ListSelectedRoutes`: `GET /projects/{project}/selectedRoutes`.
    /// Clamps `pageSize == 0 -> 100` and `> 5000 -> 5000`.
    pub fn list_selected_routes(
        &self,
        page_size: u32,
        page_token: Option<&str>,
    ) -> Result<ListSelectedRoutesResponse, RoadsSelectionError> {
        let effective_size = if page_size == 0 {
            100
        } else if page_size > 5000 {
            5000
        } else {
            page_size
        };

        let mut url = format!(
            "{}/projects/{}/selectedRoutes?pageSize={}",
            self.base_url,
            url_encode_component(&self.project_id),
            effective_size
        );
        if let Some(tok) = page_token {
            if !tok.is_empty() {
                url.push_str(&format!("&pageToken={}", url_encode_component(tok)));
            }
        }
        let val = self.dispatch("GET", url, None)?;
        let selected_routes = Self::extract_routes_array(&val)?;
        let next_page_token = match &val {
            JsonValue::Object(m) => match m.get("nextPageToken") {
                Some(JsonValue::Str(s)) if !s.is_empty() => Some(s.clone()),
                _ => None,
            },
            _ => None,
        };
        Ok(ListSelectedRoutesResponse {
            selected_routes,
            next_page_token,
        })
    }

    /// Auto-paginating helper returning all `SelectedRoute` items across pages.
    pub fn list_all_selected_routes(
        &self,
        page_size: u32,
    ) -> Result<Vec<SelectedRoute>, RoadsSelectionError> {
        let mut all = Vec::new();
        let mut token: Option<String> = None;
        loop {
            let page = self.list_selected_routes(page_size, token.as_deref())?;
            all.extend(page.selected_routes);
            match page.next_page_token {
                Some(next) if !next.is_empty() => token = Some(next),
                _ => break,
            }
        }
        Ok(all)
    }

    /// 7. `DeleteSelectedRoute`: `DELETE /projects/{project}/selectedRoutes/{id}`.
    pub fn delete_selected_route(
        &self,
        route_id_or_name: &str,
    ) -> Result<(), RoadsSelectionError> {
        let name = self.resolve_resource_name(route_id_or_name)?;
        let url = format!("{}/{}", self.base_url, name);
        self.dispatch("DELETE", url, None)?;
        Ok(())
    }

    /// 8. `BatchDeleteSelectedRoutes`: `POST /projects/{project}/selectedRoutes:batchDelete`.
    /// Omits top-level `parent` from the JSON body per Discovery `20261104`.
    pub fn batch_delete_selected_routes(
        &self,
        route_ids_or_names: &[&str],
    ) -> Result<(), RoadsSelectionError> {
        if route_ids_or_names.is_empty() || route_ids_or_names.len() > 1000 {
            return Err(RoadsSelectionError::Validation(format!(
                "BatchDeleteSelectedRoutes requires 1-1000 route names (got {})",
                route_ids_or_names.len()
            )));
        }
        let expected_prefix = format!("projects/{}/selectedRoutes/", self.project_id);
        let mut names_json = Vec::with_capacity(route_ids_or_names.len());
        for (idx, item) in route_ids_or_names.iter().enumerate() {
            let res_name = self.resolve_resource_name(item)?;
            if !res_name.starts_with(&expected_prefix) || res_name.len() <= expected_prefix.len() {
                return Err(RoadsSelectionError::Validation(format!(
                    "names[{}] '{}' must belong to project '{}'",
                    idx, res_name, self.project_id
                )));
            }
            names_json.push(json_escape_str(&res_name));
        }

        let body = format!("{{\"names\":[{}]}}", names_json.join(","));
        let url = format!(
            "{}/projects/{}/selectedRoutes:batchDelete",
            self.base_url,
            url_encode_component(&self.project_id)
        );
        self.dispatch("POST", url, Some(body))?;
        Ok(())
    }

    /// Polls `get_selected_route` until `target_state` is reached or `STATE_INVALID` / timeout occurs.
    pub fn wait_for_route_state(
        &self,
        route_id_or_name: &str,
        target_state: &str,
        timeout: Duration,
        poll_interval: Duration,
    ) -> Result<SelectedRoute, RoadsSelectionError> {
        let desired = if target_state.is_empty() {
            STATE_RUNNING
        } else {
            target_state
        };
        let start = Instant::now();
        loop {
            let route = self.get_selected_route(route_id_or_name)?;
            let current = route.state.as_deref().unwrap_or(STATE_UNSPECIFIED);
            if current == desired {
                return Ok(route);
            }
            if desired != STATE_INVALID && current == STATE_INVALID {
                let err_code = route
                    .validation_error
                    .as_deref()
                    .unwrap_or(VALIDATION_ERROR_UNSPECIFIED);
                return Err(RoadsSelectionError::Validation(format!(
                    "route entered {} (validationError={})",
                    STATE_INVALID, err_code
                )));
            }
            if start.elapsed() >= timeout {
                return Err(RoadsSelectionError::Timeout(format!(
                    "timed out waiting for {} (last state={})",
                    desired, current
                )));
            }
            thread::sleep(poll_interval);
        }
    }

    fn extract_routes_array(val: &JsonValue) -> Result<Vec<SelectedRoute>, RoadsSelectionError> {
        let obj = match val {
            JsonValue::Object(m) => m,
            _ => return Ok(Vec::new()),
        };
        match obj.get("selectedRoutes") {
            Some(JsonValue::Array(arr)) => arr.iter().map(decode_selected_route).collect(),
            _ => Ok(Vec::new()),
        }
    }
}

// =============================================================================
// Embedded Hermetic Unit & Mock Integration Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    struct MockHandlerTransport<F>
    where
        F: Fn(&HttpRequest) -> Result<HttpResponse, RoadsSelectionError>,
    {
        handler: F,
        captured: RefCell<Vec<HttpRequest>>,
    }

    impl<F> MockHandlerTransport<F>
    where
        F: Fn(&HttpRequest) -> Result<HttpResponse, RoadsSelectionError>,
    {
        fn new(handler: F) -> Self {
            Self {
                handler,
                captured: RefCell::new(Vec::new()),
            }
        }
    }

    impl<F> HttpTransport for MockHandlerTransport<F>
    where
        F: Fn(&HttpRequest) -> Result<HttpResponse, RoadsSelectionError>,
    {
        fn send(&self, req: &HttpRequest) -> Result<HttpResponse, RoadsSelectionError> {
            self.captured.borrow_mut().push(req.clone());
            (self.handler)(req)
        }
    }

    #[test]
    fn test_validate_selected_route_id_20261104() {
        assert!(validate_selected_route_id(None).is_ok());
        assert!(validate_selected_route_id(Some("")).is_ok());
        assert!(validate_selected_route_id(Some("corridor_101-nb")).is_ok());
        assert!(validate_selected_route_id(Some("ab1")).is_err());
        assert!(validate_selected_route_id(Some(&"a".repeat(64))).is_err());
        assert!(validate_selected_route_id(Some("bad@id!")).is_err());
    }

    #[test]
    fn test_validate_unicode_code_points_and_attributes() {
        let cjk40 = "東".repeat(40); // 40 code points, 120 UTF-8 bytes
        assert!(validate_display_name(&cjk40).is_ok());
        assert!(validate_display_name(&"東".repeat(101)).is_err());

        let mut attrs = BTreeMap::new();
        attrs.insert("label".to_string(), cjk40);
        attrs.insert("priority".to_string(), "HIGHWAY".to_string());
        assert!(validate_route_attributes(&attrs).is_ok());

        let mut empty_val = BTreeMap::new();
        empty_val.insert("tier".to_string(), "".to_string());
        assert!(validate_route_attributes(&empty_val).is_err());

        let mut goog_key = BTreeMap::new();
        goog_key.insert("goog_reserved".to_string(), "1".to_string());
        assert!(validate_route_attributes(&goog_key).is_err());
    }

    #[test]
    fn test_all_eight_rpcs_and_batch_contracts() {
        let get_calls = RefCell::new(0usize);
        let transport = MockHandlerTransport::new(|req| {
            assert!(req
                .headers
                .iter()
                .any(|(k, v)| k == "X-Goog-User-Project" && v == "my-roads-project"));

            if req.method == "POST" && req.url.ends_with(":batchCreate") {
                let body = req.body.as_deref().unwrap_or("");
                let parsed = parse_json(body)?;
                if let JsonValue::Object(m) = parsed {
                    assert!(
                        !m.contains_key("parent"),
                        "BatchCreateSelectedRoutesRequest must omit top-level parent"
                    );
                }
                return Ok(HttpResponse {
                    status: 200,
                    body: r#"{"selectedRoutes":[{"name":"projects/my-roads-project/selectedRoutes/seg_1","state":"STATE_VALIDATING"}]}"#.to_string(),
                });
            }

            if req.method == "POST" && req.url.ends_with(":batchUpdate") {
                let body = req.body.as_deref().unwrap_or("");
                let parsed = parse_json(body)?;
                if let JsonValue::Object(m) = parsed {
                    assert!(
                        !m.contains_key("parent"),
                        "BatchUpdateSelectedRoutesRequest must omit top-level parent"
                    );
                }
                return Ok(HttpResponse {
                    status: 200,
                    body: r#"{"selectedRoutes":[{"name":"projects/my-roads-project/selectedRoutes/seg_1","state":"STATE_RUNNING"}]}"#.to_string(),
                });
            }

            if req.method == "POST" && req.url.ends_with(":batchDelete") {
                let body = req.body.as_deref().unwrap_or("");
                let parsed = parse_json(body)?;
                if let JsonValue::Object(m) = parsed {
                    assert!(
                        !m.contains_key("parent"),
                        "BatchDeleteSelectedRoutesRequest must omit top-level parent"
                    );
                }
                return Ok(HttpResponse {
                    status: 200,
                    body: "{}".to_string(),
                });
            }

            if req.method == "POST" && req.url.contains("/selectedRoutes") {
                return Ok(HttpResponse {
                    status: 200,
                    body: r#"{"name":"projects/my-roads-project/selectedRoutes/corridor_1","displayName":"Market St","dynamicRouting":false,"state":"STATE_VALIDATING"}"#.to_string(),
                });
            }

            if req.method == "GET" && req.url.ends_with("/selectedRoutes/corridor_1") {
                let mut count = get_calls.borrow_mut();
                *count += 1;
                let st = if *count >= 2 {
                    "STATE_RUNNING"
                } else {
                    "STATE_VALIDATING"
                };
                return Ok(HttpResponse {
                    status: 200,
                    body: format!(
                        r#"{{"name":"projects/my-roads-project/selectedRoutes/corridor_1","state":"{}"}}"#,
                        st
                    ),
                });
            }

            if req.method == "PATCH" && req.url.contains("/selectedRoutes/corridor_1") {
                assert!(req.url.contains("updateMask="));
                return Ok(HttpResponse {
                    status: 200,
                    body: r#"{"name":"projects/my-roads-project/selectedRoutes/corridor_1","displayName":"Patched","dynamicRouting":true,"state":"STATE_RUNNING"}"#.to_string(),
                });
            }

            if req.method == "GET" && req.url.contains("/selectedRoutes?pageSize=5000") {
                if req.url.contains("pageToken=p2") {
                    return Ok(HttpResponse {
                        status: 200,
                        body: r#"{"selectedRoutes":[{"name":"projects/my-roads-project/selectedRoutes/seg_2"}]}"#.to_string(),
                    });
                }
                return Ok(HttpResponse {
                    status: 200,
                    body: r#"{"selectedRoutes":[{"name":"projects/my-roads-project/selectedRoutes/seg_1"}],"nextPageToken":"p2"}"#.to_string(),
                });
            }

            if req.method == "DELETE" {
                return Ok(HttpResponse {
                    status: 200,
                    body: "{}".to_string(),
                });
            }

            Err(RoadsSelectionError::Transport(format!(
                "unexpected URL: {} {}",
                req.method, req.url
            )))
        });

        let client = RoadsSelectionClient::with_transport(
            "my-roads-project",
            "my-roads-project",
            DEFAULT_BASE_URL,
            Some("test-rs-token".to_string()),
            transport,
        )
        .unwrap();

        let dr = DynamicRoute::new(
            LatLng::new(37.7749, -122.4194),
            LatLng::new(37.7833, -122.4067),
        );
        let mut attrs = BTreeMap::new();
        attrs.insert("corridor".to_string(), "market_st".to_string());

        let created = client
            .create_selected_route(
                Some("corridor_1"),
                &SelectedRoute {
                    display_name: Some("Market St".to_string()),
                    dynamic_route: Some(dr.clone()),
                    dynamic_routing: Some(false),
                    route_attributes: attrs,
                    ..SelectedRoute::default()
                },
            )
            .unwrap();
        assert_eq!(created.dynamic_routing, Some(false));

        let batch_created = client
            .batch_create_selected_routes(&[CreateRouteInput {
                parent: None,
                selected_route_id: Some("seg_1".to_string()),
                selected_route: SelectedRoute {
                    display_name: Some("Seg 1".to_string()),
                    dynamic_route: Some(dr),
                    ..SelectedRoute::default()
                },
            }])
            .unwrap();
        assert_eq!(batch_created.len(), 1);

        let running = client
            .wait_for_route_state(
                "corridor_1",
                STATE_RUNNING,
                Duration::from_secs(2),
                Duration::from_millis(5),
            )
            .unwrap();
        assert_eq!(running.state.as_deref(), Some(STATE_RUNNING));

        let patched = client
            .update_selected_route(
                "corridor_1",
                &SelectedRoute {
                    display_name: Some("Patched".to_string()),
                    dynamic_routing: Some(true),
                    ..SelectedRoute::default()
                },
                None,
            )
            .unwrap();
        assert_eq!(patched.dynamic_routing, Some(true));

        // Mismatched child vs batch updateMask must fail client-side validation
        let mismatch = client.batch_update_selected_routes(
            &[UpdateRouteInput {
                selected_route: SelectedRoute {
                    name: Some("projects/my-roads-project/selectedRoutes/seg_1".to_string()),
                    display_name: Some("Seg 1".to_string()),
                    ..SelectedRoute::default()
                },
                update_mask: Some("displayName".to_string()),
            }],
            Some("displayName,routeAttributes"),
        );
        assert!(mismatch.is_err());

        let batch_updated = client
            .batch_update_selected_routes(
                &[UpdateRouteInput {
                    selected_route: SelectedRoute {
                        name: Some("projects/my-roads-project/selectedRoutes/seg_1".to_string()),
                        display_name: Some("Seg 1".to_string()),
                        ..SelectedRoute::default()
                    },
                    update_mask: None,
                }],
                Some("displayName"),
            )
            .unwrap();
        assert_eq!(batch_updated.len(), 1);

        let listed = client.list_all_selected_routes(9000).unwrap();
        assert_eq!(listed.len(), 2);

        client.delete_selected_route("corridor_1").unwrap();
        client.batch_delete_selected_routes(&["seg_1"]).unwrap();
    }

    #[test]
    fn test_live_mock_server_roundtrips() {
        let mock_base = match env::var("MOCK_ROADS_BASE_URL") {
            Ok(v) if !v.trim().is_empty() => v,
            _ => return,
        };
        let client = RoadsSelectionClient::with_transport(
            "proj-rs",
            "proj-rs",
            mock_base,
            Some("mock-rs-token".to_string()),
            CommandCurlTransport,
        )
        .unwrap();

        let dr = DynamicRoute::new(
            LatLng::new(37.7749, -122.4194),
            LatLng::new(37.7833, -122.4067),
        );
        let mut attrs = BTreeMap::new();
        attrs.insert("lang".to_string(), "rust".to_string());

        let created = client
            .create_selected_route(
                Some("rs_corridor_01"),
                &SelectedRoute {
                    display_name: Some("Rust Corridor 01".to_string()),
                    dynamic_route: Some(dr.clone()),
                    dynamic_routing: Some(false),
                    route_attributes: attrs,
                    ..SelectedRoute::default()
                },
            )
            .unwrap();
        assert_eq!(
            created.name.as_deref(),
            Some("projects/proj-rs/selectedRoutes/rs_corridor_01")
        );

        let running = client
            .wait_for_route_state(
                "rs_corridor_01",
                STATE_RUNNING,
                Duration::from_secs(5),
                Duration::from_millis(50),
            )
            .unwrap();
        assert_eq!(running.state.as_deref(), Some(STATE_RUNNING));

        let patched = client
            .update_selected_route(
                "rs_corridor_01",
                &SelectedRoute {
                    display_name: Some("Rust Corridor 01 Patched".to_string()),
                    dynamic_routing: Some(true),
                    ..SelectedRoute::default()
                },
                Some("displayName,dynamicRouting"),
            )
            .unwrap();
        assert_eq!(
            patched.display_name.as_deref(),
            Some("Rust Corridor 01 Patched")
        );

        let batch_created = client
            .batch_create_selected_routes(&[
                CreateRouteInput {
                    parent: None,
                    selected_route_id: Some("rs_batch_1".to_string()),
                    selected_route: SelectedRoute {
                        display_name: Some("Rust Batch 1".to_string()),
                        dynamic_route: Some(dr.clone()),
                        ..SelectedRoute::default()
                    },
                },
                CreateRouteInput {
                    parent: None,
                    selected_route_id: Some("rs_batch_2".to_string()),
                    selected_route: SelectedRoute {
                        display_name: Some("Rust Batch 2".to_string()),
                        dynamic_route: Some(dr),
                        ..SelectedRoute::default()
                    },
                },
            ])
            .unwrap();
        assert_eq!(batch_created.len(), 2);

        let batch_updated = client
            .batch_update_selected_routes(
                &[UpdateRouteInput {
                    selected_route: SelectedRoute {
                        name: Some("projects/proj-rs/selectedRoutes/rs_batch_1".to_string()),
                        display_name: Some("Rust Batch 1 v2".to_string()),
                        ..SelectedRoute::default()
                    },
                    update_mask: None,
                }],
                Some("displayName"),
            )
            .unwrap();
        assert_eq!(batch_updated.len(), 1);

        let all = client.list_all_selected_routes(100).unwrap();
        assert!(all.len() >= 3);

        client
            .batch_delete_selected_routes(&["rs_batch_1", "rs_batch_2"])
            .unwrap();
        client.delete_selected_route("rs_corridor_01").unwrap();
    }
}
