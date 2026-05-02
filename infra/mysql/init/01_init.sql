-- =============================================================================
-- SupplyChainForge — MySQL Initialization Script
-- Runs once when the MySQL container is first created.
-- Creates per-service databases and users with least-privilege grants.
-- =============================================================================

-- ── Inventory Service ─────────────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS inventory_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'inventory_user'@'%' IDENTIFIED BY 'inventory_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP ON inventory_db.* TO 'inventory_user'@'%';

-- ── Order Service (stub — created now so the DB exists for Phase 2) ───────────
CREATE DATABASE IF NOT EXISTS order_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'order_user'@'%' IDENTIFIED BY 'order_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP ON order_db.* TO 'order_user'@'%';

-- ── Fulfillment Service (stub) ────────────────────────────────────────────────
CREATE DATABASE IF NOT EXISTS fulfillment_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'fulfillment_user'@'%' IDENTIFIED BY 'fulfillment_password';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP ON fulfillment_db.* TO 'fulfillment_user'@'%';

FLUSH PRIVILEGES;
