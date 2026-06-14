# MCP Server Dashboard – Requirements Document

## 1. Overview

### 1.1 Purpose
The MCP Server Dashboard is an open-source application that provides a unified interface for discovering, configuring, and managing Model Context Protocol (MCP) connectors and tools. It enables users to connect diverse data sources (file systems, databases, REST APIs) to AI clients through MCP, exposing data as queryable resources via standardized MCP tools.

### 1.2 Scope
This requirements document covers all functional and non-functional aspects of the MCP Server Dashboard, including:
- Backend services (Python FastAPI application)
- Frontend interface (React 18 single-page application)
- Connector management (Folder, DuckDB, SQLite, REST API)
- MCP bridge and tool exposure
- Authentication, authorization, and security
- Cross-platform service installation and management
- Configuration and data import/export

### 1.3 Target Audience
- Data engineers and analysts integrating with AI workflows
- System administrators managing MCP server deployments
- Developers building AI applications requiring standardized data access
- Open-source community members extending the platform

---

## 2. Functional Requirements

### 2.1 Source/Connector Management

| ID | Requirement | Description |
|----|-----------|----|
| FR-1.1 | Folder Connector | Support reading CSV, JSON, Parquet, and Excel files from user-specified directories via DuckDB query engine |
| FR-1.2 | DuckDB Connector | Enable direct connection to DuckDB database files with full SQL query capabilities |
| FR-1.3 | SQLite Connector | Support SQLite database connections with schema discovery and querying |
| FR-1.4 | REST API Connector | Allow configuration of REST endpoints as queryable data sources with request templating |
| FR-1.5 | Connector CRUD Operations | Provide create, read, update, and delete operations for all connector types via REST API |
| FR-1.6 | Schema Discovery | Automatically detect and expose table/dataset schemas for all connector types |
| FR-1.7 | Test Connection | Validate connector configuration before saving with meaningful error messages |
| FR-1.8 | Connector Listing | Display all configured connectors with connection status and last-used timestamp |

### 2.2 MCP Bridge & Tool Exposure

| ID | Requirement | Description |
|----|-----------|----|
| FR-2.1 | FastMCP Integration | Integrate MCP bridge using FastMCP SDK with stdio transport for AI client communication |
| FR-2.2 | Query Tool | Expose 9 MCP tools allowing AI clients to execute queries across configured connectors |
| FR-2.3 | Tool Schema Definitions | Each MCP tool includes JSON schema with parameter validation and return type specification |
| FR-2.4 | Query Execution | Execute parameterized queries against selected connectors with configurable timeout (default 30s) |
| FR-2.5 | Result Pagination | Support paginated result sets for large query outputs (configurable page size, default 1000 rows) |
| FR-2.6 | Tool Error Handling | Return structured error codes and descriptive messages when tool execution fails |
| FR-2.7 | Tool Capability Discovery | Advertise available tools and their parameters to MCP clients during initialization |

### 2.3 Dashboard User Interface

| ID | Requirement | Description |
|----|-----------|----|
| FR-3.1 | Single-File Frontend | Implement React 18 frontend as single HTML file using Babel standalone (no build step) |
| FR-3.2 | Connector List View | Display all connectors with type, status, configuration summary, and action buttons |
| FR-3.3 | Connector Detail View | Show detailed connector configuration, schema preview, and edit/test controls |
| FR-3.4 | Connector Creation Form | Provide forms for adding new connectors with field validation and type-specific options |
| FR-3.5 | Query Builder/Console | Enable ad-hoc query execution against any connector with result display and export |
| FR-3.6 | Health Status Display | Show real-time MCP service status, uptime, and recent activity |
| FR-3.7 | Configuration Manager | Display current configuration settings and allow modification where applicable |
| FR-3.8 | Headless Mode Detection | Gracefully handle deployments without browser access (service-only mode) |
| FR-3.9 | Health Polling | Poll backend health status every 45 seconds and update UI accordingly |

### 2.4 Authentication & Security

| ID | Requirement | Description |
|----|-----------|----|
| FR-4.1 | Optional API Key Auth | Support optional API key authentication via header (X-API-Key) or query parameter |
| FR-4.2 | API Key Configuration | Allow users to generate, rotate, and revoke API keys |
| FR-4.3 | Rate Limiting | Enforce rate limiting of 120 requests per minute per IP address |
| FR-4.4 | Rate Limit Headers | Return standard rate-limit headers (X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset) |
| FR-4.5 | Read-Only Enforcement | Block execution of SQL statements containing write keywords (INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE) |
| FR-4.6 | SQL Keyword Filtering | Implement case-insensitive keyword detection across all SQL dialects |
| FR-4.7 | Error Responses | Return consistent error codes (4xx for client errors, 5xx for server errors) without exposing internal details |

### 2.5 Configuration Management

| ID | Requirement | Description |
|----|-----------|----|
| FR-5.1 | OS-Standard Config Dirs | Store configuration in platform-specific directories: macOS ~/Library/Application Support/MCP-Server/, Linux ~/.config/mcp-server/, Windows %APPDATA%/MCP-Server/ |
| FR-5.2 | Configuration File | Persist connector definitions and settings in standard location accessible across sessions |
| FR-5.3 | Import Connector Config | Allow users to import connector configurations from JSON files |
| FR-5.4 | Export Connector Config | Enable export of all or selected connector configurations as JSON |
| FR-5.5 | Config Validation | Validate imported configurations before applying to prevent runtime errors |
| FR-5.6 | Config Backup | Create automatic backups before modifying configuration |
| FR-5.7 | Environment Variable Support | Allow sensitive values (API keys, passwords) to be specified via environment variables |

### 2.6 Service Installation & Cross-Platform Support

| ID | Requirement | Description |
|----|-----------|----|
| FR-6.1 | macOS LaunchAgent Installation | Provide installer to register MCP server as LaunchAgent for automatic startup |
| FR-6.2 | Linux Systemd User Service | Support systemd user service installation for automatic startup on Linux |
| FR-6.3 | Windows Task Scheduler | Enable Windows Task Scheduler registration for automatic startup |
| FR-6.4 | Service Status Commands | Provide CLI commands to start, stop, restart, and check service status |
| FR-6.5 | Auto-Start Configuration | Allow users to enable/disable automatic startup on system boot |
| FR-6.6 | Service Logging | Capture service logs with configurable log level and rotation |
| FR-6.7 | Uninstall Support | Provide clean uninstall that removes service registration and optionally preserves/removes configuration |

### 2.7 API Endpoints

The application exposes 22 REST API endpoints organized by function:

**Connector Management (8 endpoints)**
- `GET /api/connectors` – List all connectors
- `POST /api/connectors` – Create new connector
- `GET /api/connectors/{id}` – Get connector details
- `PUT /api/connectors/{id}` – Update connector configuration
- `DELETE /api/connectors/{id}` – Delete connector
- `POST /api/connectors/{id}/test` – Test connector connectivity
- `GET /api/connectors/{id}/schema` – Get connector schema
- `POST /api/connectors/{id}/query` – Execute query on connector

**Query Execution (4 endpoints)**
- `POST /api/query` – Execute ad-hoc query (requires connector_id parameter)
- `POST /api/query/explain` – Explain query execution plan
- `GET /api/query/history` – Retrieve recent query history
- `DELETE /api/query/history/{id}` – Clear query from history

**Configuration (4 endpoints)**
- `GET /api/config` – Retrieve current configuration
- `PUT /api/config` – Update configuration
- `POST /api/config/export` – Export configurations as JSON
- `POST /api/config/import` – Import configurations from JSON

**Authentication (2 endpoints)**
- `POST /api/auth/keys` – Generate new API key
- `DELETE /api/auth/keys/{key_id}` – Revoke API key

**Health & Status (4 endpoints)**
- `GET /api/health` – Check service health status
- `GET /api/status` – Detailed service status including uptime
- `GET /api/version` – Get application version
- `GET /api/metrics` – Retrieve service metrics (requests, query performance)

---

## 3. Non-Functional Requirements

### 3.1 Performance

| ID | Requirement | Description |
|----|-----------|----|
| NFR-1.1 | Query Timeout | Enforce maximum query execution time of 30 seconds (configurable) |
| NFR-1.2 | Result Pagination | Return paginated result sets (default 1000 rows per page) to prevent memory exhaustion |
| NFR-1.3 | Concurrent Connections | Support minimum 10 concurrent user connections without degradation |
| NFR-1.4 | API Response Time | 95th percentile API response time under 500ms for connector CRUD operations |
| NFR-1.5 | Query Performance | Complex analytical queries return within 30 seconds under typical load |
| NFR-1.6 | Large File Support | Support importing Parquet/CSV files up to 500MB through Folder connector |
| NFR-1.7 | Memory Efficiency | Streaming result processing to prevent in-memory materialization of large datasets |

### 3.2 Reliability

| ID | Requirement | Description |
|----|-----------|----|
| NFR-2.1 | Service Uptime | Target 99.5% uptime for background service when properly installed as system service |
| NFR-2.2 | Graceful Degradation | Frontend remains functional even if health polling fails temporarily |
| NFR-2.3 | Configuration Persistence | Configuration changes persist across service restarts |
| NFR-2.4 | Connection Pooling | Maintain connection pools for database connectors to improve reliability and performance |
| NFR-2.5 | Automatic Reconnection | Attempt automatic reconnection to databases with exponential backoff (max 60s) |
| NFR-2.6 | Error Recovery | Log all errors and provide recovery suggestions in UI and logs |
| NFR-2.7 | Backup Before Modification | Create timestamped configuration backups before any modification operation |

### 3.3 Portability & Compatibility

| ID | Requirement | Description |
|----|-----------|----|
| NFR-3.1 | Python 3.10+ Support | Require Python 3.10 or higher; test against 3.10, 3.11, 3.12 |
| NFR-3.2 | macOS Compatibility | Support macOS 11.0+ (Intel and Apple Silicon) |
| NFR-3.3 | Linux Compatibility | Support Ubuntu 20.04+, CentOS 8+, and other systemd-based distributions |
| NFR-3.4 | Windows Compatibility | Support Windows 10/11 with Python 3.10+ from python.org or Microsoft Store |
| NFR-3.5 | Docker Support | Provide Dockerfile for containerized deployment (optional) |
| NFR-3.6 | Port Binding | Backend runs on port 8420; frontend served from same port via HTTP |
| NFR-3.7 | Network Isolation | Support localhost-only operation by default; configurable for network access |
| NFR-3.8 | Browser Compatibility | React frontend compatible with Chrome 90+, Firefox 88+, Safari 14+, Edge 90+ |

### 3.4 Security

| ID | Requirement | Description |
|----|-----------|----|
| NFR-4.1 | HTTPS Support | Support TLS/HTTPS with optional self-signed certificate generation |
| NFR-4.2 | API Key Security | Hash API keys using bcrypt (min 12 rounds); never log plaintext keys |
| NFR-4.3 | Password Masking | Mask sensitive credentials (passwords, API keys) in logs and UI previews |
| NFR-4.4 | SQL Injection Prevention | Parameterize all SQL queries; never concatenate user input into SQL strings |
| NFR-4.5 | CORS Configuration | Restrict Cross-Origin Resource Sharing to trusted origins; deny by default for remote access |
| NFR-4.6 | Input Validation | Validate all API inputs against schemas; reject oversized payloads (>10MB) |
| NFR-4.7 | Sensitive Data Handling | Implement read-only enforcement to prevent accidental data modification |
| NFR-4.8 | Audit Logging | Log all authentication attempts, configuration changes, and query execution with timestamps |
| NFR-4.9 | Secret Rotation | Support rotating API keys and database credentials without downtime |

### 3.5 Usability

| ID | Requirement | Description |
|----|-----------|----|
| NFR-5.1 | Intuitive UI | Dashboard provides clear visual hierarchy; users can configure first connector in <5 minutes |
| NFR-5.2 | Error Messages | All errors include specific, actionable guidance; no generic "Error" messages |
| NFR-5.3 | Documentation | Provide in-app help, tooltips, and link to comprehensive documentation |
| NFR-5.4 | Accessibility | Dashboard meets WCAG 2.1 Level AA standards for accessibility |
| NFR-5.5 | Responsive Design | UI adapts gracefully to screen sizes from 1024px to 4K; mobile-friendly where practical |
| NFR-5.6 | Dark Mode | Support light and dark theme options with preference persistence |
| NFR-5.7 | Keyboard Navigation | All dashboard functions accessible via keyboard without mouse |
| NFR-5.8 | Visual Feedback | Provide loading indicators, success confirmations, and error highlights |

### 3.6 Maintainability & Testing

| ID | Requirement | Description |
|----|-----------|----|
| NFR-6.1 | Code Organization | Separate concerns into distinct modules (models, routes, services, utils) |
| NFR-6.2 | Type Hints | Use Python type hints throughout codebase for improved maintainability |
| NFR-6.3 | Test Coverage | Maintain minimum 80% test coverage; critical paths tested with unit and integration tests |
| NFR-6.4 | Documentation | Code includes docstrings for all public functions; API endpoints documented with examples |
| NFR-6.5 | Dependency Management | Pin dependency versions in requirements.txt with regular security updates |
| NFR-6.6 | CI/CD Integration | Support automated testing and linting in CI/CD pipelines |
| NFR-6.7 | Logging | Implement structured logging with appropriate log levels (DEBUG, INFO, WARNING, ERROR) |

---

## 4. System Requirements

### 4.1 Runtime Environment

| Requirement | Specification |
|-------------|---|
| Python Version | 3.10, 3.11, 3.12, or later |
| Operating System | macOS 11.0+, Linux (systemd), Windows 10/11 |
| Processor | x86-64 or ARM64 (Apple Silicon) |
| Memory | Minimum 256MB; recommended 512MB for typical workloads |
| Storage | Minimum 100MB for application; variable space for data caches |
| Network | TCP port 8420 for HTTP server; configurable for network access |

### 4.2 Python Dependencies

**Core Dependencies**
- `fastapi>=0.104` – Web framework
- `uvicorn>=0.24` – ASGI server
- `pydantic>=2.0` – Data validation and serialization
- `duckdb>=0.9` – Query engine for file-based data
- `httpx>=0.25` – HTTP client for REST API connector
- `psutil>=5.9` – System monitoring and service management
- `mcp>=1.0` – Model Context Protocol SDK

**Development/Testing Dependencies**
- `pytest>=7.0` – Testing framework
- `pytest-cov>=4.0` – Coverage reporting
- `black` – Code formatting
- `ruff` – Linting
- `mypy>=1.0` – Type checking

### 4.3 Frontend Dependencies

- React 18+ (via CDN, no build step)
- Babel Standalone (for JSX transformation)
- Fetch API (built-in browser API)

---

## 5. Constraints and Assumptions

### 5.1 Constraints

| ID | Constraint | Impact |
|----|-----------|----|
| C-1 | Read-Only Operations | All data modifications blocked to prevent accidental data loss; users cannot use MCP for ETL operations |
| C-2 | Single-File Frontend | Frontend cannot be built with webpack/vite; limits build optimization opportunities |
| C-3 | Stdio Transport | MCP communication limited to stdio; no network-based MCP transport in this version |
| C-4 | Localhost Default | Security-first approach runs on localhost by default; network deployment requires explicit configuration |
| C-5 | Configuration Directory Immutability | Config directory paths fixed per OS; difficult to relocate after initial setup |
| C-6 | Port 8420 Fixed | Backend bound to specific port; cannot coexist with other services on same port |
| C-7 | API Key Requirement | Authentication is optional but recommended; unsecured deployments expose all data |

### 5.2 Assumptions

| ID | Assumption | Rationale |
|----|-----------|----|
| A-1 | Users Have Python 3.10+ | Open-source targeting technical users who manage Python environments |
| A-2 | Single-User Deployment | Initial version designed for single-user or small-team deployments; not multi-tenant |
| A-3 | Trusted Network | No assumption of hostile network; users responsible for network security in multi-user environments |
| A-4 | Read-Only Use Cases | Users won't require write operations; MCP serves as read-only analytics interface |
| A-5 | Modern Browser | Users will access frontend via modern browser with ES6+ JavaScript support |
| A-6 | Standard File Formats | CSV, JSON, Parquet files follow standard specifications; corrupted files may fail silently |
| A-7 | Database Availability | Connected databases remain available throughout service operation; manual reconnection required on failure |
| A-8 | REST API Stability | Third-party REST APIs don't change schemas without notice; users responsible for updating configs |

---

## 6. Future Considerations

### 6.1 Planned Features (Not in Scope)

The following features are identified as valuable for future releases but not included in the current scope:

#### 6.1.1 Additional Connectors
- **PostgreSQL Connector** – Direct connection to PostgreSQL databases
- **MySQL/MariaDB Connector** – Support for MySQL-compatible databases
- **MongoDB Connector** – NoSQL document querying
- **Apache Kafka Connector** – Event streaming data source
- **Cloud Storage Connectors** – S3, GCS, Azure Blob Storage integration
- **Snowflake Connector** – Cloud data warehouse support

#### 6.1.2 Advanced Features
- **Webhook Notifications** – Trigger notifications when data changes in sources
- **Scheduled Queries** – Define and execute queries on a schedule
- **Query Templates** – Save and reuse common query patterns
- **Data Profiling** – Automatic schema analysis and data quality metrics
- **Performance Metrics Dashboard** – Visualize query performance trends
- **Multi-User Authentication** – OAuth2 / SSO integration for team deployments
- **Data Governance** – Role-based access control (RBAC) and column-level security
- **Caching Layer** – Redis or in-memory caching for frequently accessed datasets

#### 6.1.3 Operational Features
- **Distributed Deployment** – Load balancing across multiple instances
- **Health Checks & Alerts** – Proactive monitoring and alerting
- **Query Versioning** – Track history of query definitions
- **Audit Dashboard** – Visual review of access logs and modifications
- **Configuration Sync** – Synchronize configurations across instances
- **Automatic Backups** – Scheduled backup and restore capability

#### 6.1.4 Performance Optimization
- **Query Optimization Engine** – Automatic query rewriting for performance
- **Index Management** – Automatic index suggestions for database connectors
- **Compression** – Result set compression for large responses
- **GraphQL Support** – Alternative query interface for specific use cases

#### 6.1.5 Developer Experience
- **CLI Tool** – Command-line interface for connector management
- **Terraform Provider** – Infrastructure-as-code support
- **Python SDK** – Programmatic connector management from Python
- **Webhooks for Integration** – Event-driven integration with external systems

### 6.2 Extensibility Points

The architecture should be designed to allow future extension in these areas:
- **Connector Plugin System** – Allow third-party developers to create custom connectors
- **Tool Middleware** – Support custom processing logic between MCP and data sources
- **Event Hooks** – Pre/post execution hooks for queries and configuration changes
- **Custom Authenticators** – Support for alternative authentication schemes beyond API keys

### 6.3 Success Metrics for Future Releases

When evaluating future feature additions, consider:
- **Adoption Rate** – Number of unique users and deployments
- **Feature Usage** – Which connectors and tools are most frequently used
- **Performance Bottlenecks** – Identified limitations in current implementation
- **Community Feedback** – Issues and feature requests from users
- **Integration Needs** – Requirements from AI platform integrations

---

## Appendix: Glossary

| Term | Definition |
|------|-----------|
| **Connector** | A configuration that defines how to access an external data source (Folder, DuckDB, SQLite, REST API) |
| **MCP Tool** | A standardized interface exposing connector functionality to AI clients; 9 tools total in this version |
| **Stdio Transport** | MCP communication protocol using standard input/output streams |
| **Query Timeout** | Maximum time allowed for a query to execute before termination (default 30s) |
| **Rate Limiting** | Mechanism to restrict number of requests per IP address (120 req/min) |
| **Read-Only Enforcement** | Security layer preventing execution of write operations (INSERT, UPDATE, DELETE, etc.) |
| **Headless Mode** | Service running without browser interface (e.g., as systemd service) |
| **Health Polling** | Frontend mechanism to check backend status every 45 seconds |
| **API Key** | Authentication credential used to secure API access |
| **Schema Discovery** | Automatic detection and exposure of table structures and data types |

---

**Document Version:** 1.0  
**Last Updated:** 2026-04-13  
**Status:** Complete and Approved
