import { ApiProvider } from "@/api/provider";
import type { ApiClient } from "@/api/client";
import { AuthGate } from "@/features/auth/AuthGate";
import { AppShell } from "@/features/shell/AppShell";
import { ShellProvider } from "@/features/shell/ShellProvider";

/** `client` si passa solo nei test; altrimenti lo sceglie `VITE_API_MODE`. */
export default function App({ client }: { client?: ApiClient }) {
  return (
    <ApiProvider client={client}>
      <AuthGate>
        <ShellProvider>
          <AppShell />
        </ShellProvider>
      </AuthGate>
    </ApiProvider>
  );
}
