import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ConfigProvider, App as AntApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import AdminLayout from "./layouts/AdminLayout";
import ReplayPage from "./pages/ReplayPage";
import SymbolsPage from "./pages/SymbolsPage";
import SyncPage from "./pages/SyncPage";

/**
 * 路由：/zq/ 复盘、/zq/symbols 关注股、/zq/sync 同步管理。
 * basename 与 Vite base、Nginx location /zq/ 一致。
 */
export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#1677ff",
          borderRadius: 6,
        },
      }}
    >
      <AntApp>
        <BrowserRouter basename="/zq">
          <Routes>
            <Route element={<AdminLayout />}>
              <Route index element={<ReplayPage />} />
              <Route path="symbols" element={<SymbolsPage />} />
              <Route path="sync" element={<SyncPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  );
}
