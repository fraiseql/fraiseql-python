-- RBAC Row-Level Security Migration
-- Helper functions for RLS policies, and example policies for tables named users,
-- orders and products.
--
-- Requires 002_rbac_tables.sql. The two functions are always created. The policies of
-- each example table are applied only if that table exists (in the search_path) when
-- this file runs; a missing table is skipped with a NOTICE, and the file can be run
-- again once it exists. The example policies read these columns:
--   users:    id, tenant_id
--   orders:   tenant_id, user_id
--   products: tenant_id
-- and the session variables app.tenant_id, app.user_id and app.is_super_admin.

-- Function to check if user has role (for use in policies)
CREATE OR REPLACE FUNCTION user_has_role(p_user_id UUID, p_role_name TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM user_roles ur
        INNER JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = p_user_id
        AND r.name = p_role_name
        AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to check if user has permission (for use in policies)
CREATE OR REPLACE FUNCTION user_has_permission(p_user_id UUID, p_resource TEXT, p_action TEXT)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1
        FROM user_roles ur
        INNER JOIN roles r ON ur.role_id = r.id
        INNER JOIN role_permissions rp ON r.id = rp.role_id
        INNER JOIN permissions p ON rp.permission_id = p.id
        WHERE ur.user_id = p_user_id
        AND p.resource = p_resource
        AND p.action = p_action
        AND rp.granted = TRUE
        AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
    );
END;
$$ LANGUAGE plpgsql STABLE;

-- users: tenant isolation, and updates of one's own row unless admin
DO $$
BEGIN
    IF to_regclass('users') IS NULL THEN
        RAISE NOTICE 'users table does not exist - skipping its RLS policies';
        RETURN;
    END IF;

    ALTER TABLE users ENABLE ROW LEVEL SECURITY;

    -- Users can only see data from their tenant, unless they are super admin
    DROP POLICY IF EXISTS tenant_isolation_users ON users;
    CREATE POLICY tenant_isolation_users ON users
        FOR ALL
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::UUID
            OR current_setting('app.is_super_admin', TRUE)::BOOLEAN
        );

    -- Users can only modify their own data, unless they are admin or super_admin
    DROP POLICY IF EXISTS own_data_update_users ON users;
    CREATE POLICY own_data_update_users ON users
        FOR UPDATE
        USING (
            id = current_setting('app.user_id', TRUE)::UUID
            OR EXISTS (
                SELECT 1 FROM user_roles ur
                INNER JOIN roles r ON ur.role_id = r.id
                WHERE ur.user_id = current_setting('app.user_id', TRUE)::UUID
                AND r.name IN ('admin', 'super_admin')
            )
        );

    CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id);
END $$;

-- orders: tenant isolation, and updates of one's own orders unless admin
DO $$
BEGIN
    IF to_regclass('orders') IS NULL THEN
        RAISE NOTICE 'orders table does not exist - skipping its RLS policies';
        RETURN;
    END IF;

    ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS tenant_isolation_orders ON orders;
    CREATE POLICY tenant_isolation_orders ON orders
        FOR ALL
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::UUID
            OR current_setting('app.is_super_admin', TRUE)::BOOLEAN
        );

    -- Users can modify orders they own, or all orders if admin
    DROP POLICY IF EXISTS own_data_update_orders ON orders;
    CREATE POLICY own_data_update_orders ON orders
        FOR UPDATE
        USING (
            user_id = current_setting('app.user_id', TRUE)::UUID
            OR EXISTS (
                SELECT 1 FROM user_roles ur
                INNER JOIN roles r ON ur.role_id = r.id
                WHERE ur.user_id = current_setting('app.user_id', TRUE)::UUID
                AND r.name IN ('admin', 'super_admin')
            )
        );

    CREATE INDEX IF NOT EXISTS idx_orders_tenant_id ON orders(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
END $$;

-- products: global or tenant-scoped, managed by admins
DO $$
BEGIN
    IF to_regclass('products') IS NULL THEN
        RAISE NOTICE 'products table does not exist - skipping its RLS policies';
        RETURN;
    END IF;

    ALTER TABLE products ENABLE ROW LEVEL SECURITY;

    DROP POLICY IF EXISTS tenant_isolation_products ON products;
    CREATE POLICY tenant_isolation_products ON products
        FOR ALL
        USING (
            tenant_id = current_setting('app.tenant_id', TRUE)::UUID
            OR tenant_id IS NULL  -- Global products
            OR current_setting('app.is_super_admin', TRUE)::BOOLEAN
        );

    -- Only admins can create/modify products
    DROP POLICY IF EXISTS product_management ON products;
    CREATE POLICY product_management ON products
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM user_roles ur
                INNER JOIN roles r ON ur.role_id = r.id
                WHERE ur.user_id = current_setting('app.user_id', TRUE)::UUID
                AND r.name IN ('admin', 'super_admin')
            )
        );

    CREATE INDEX IF NOT EXISTS idx_products_tenant_id ON products(tenant_id);
END $$;
