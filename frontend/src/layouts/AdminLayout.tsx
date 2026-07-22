/**
 * 后台管理壳：左侧菜单 + 顶栏 + 内容区。
 * 菜单对应回放 / 关注股 / 同步三块能力，与原先单页抽屉拆分对齐。
 */

import { useMemo, useState } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { Layout, Menu, Typography, theme } from "antd";
import {
  LineChartOutlined,
  StockOutlined,
  CloudSyncOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";

const { Header, Sider, Content } = Layout;

const MENU_ITEMS = [
  { key: "/", icon: <LineChartOutlined />, label: "分时复盘" },
  { key: "/symbols", icon: <StockOutlined />, label: "关注股票" },
  { key: "/sync", icon: <CloudSyncOutlined />, label: "同步管理" },
];

export default function AdminLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();

  const selected = useMemo(() => {
    const path = location.pathname;
    if (path.startsWith("/symbols")) return "/symbols";
    if (path.startsWith("/sync")) return "/sync";
    return "/";
  }, [location.pathname]);

  const title = MENU_ITEMS.find((m) => m.key === selected)?.label ?? "分时复盘归档";

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        trigger={null}
        theme="dark"
        width={208}
      >
        <div
          style={{
            height: 56,
            margin: 12,
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "flex-start",
            gap: 8,
            color: "#fff",
            fontWeight: 600,
            fontSize: collapsed ? 14 : 15,
            whiteSpace: "nowrap",
            overflow: "hidden",
          }}
        >
          {collapsed ? "复盘" : "分时复盘归档"}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selected]}
          items={MENU_ITEMS}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            padding: "0 20px",
            background: token.colorBgContainer,
            display: "flex",
            alignItems: "center",
            gap: 12,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              fontSize: 18,
              display: "inline-flex",
              padding: 4,
            }}
            aria-label={collapsed ? "展开菜单" : "收起菜单"}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
          <Typography.Title level={5} style={{ margin: 0 }}>
            {title}
          </Typography.Title>
        </Header>
        <Content style={{ margin: 16, minHeight: 280 }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
