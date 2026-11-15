import type { ReactNode } from "react";
import { useMe } from "@/api/queries";
import { Button } from "@/components/Button";
import { LoginPage } from "@/features/auth/LoginPage";
import { strings } from "@/i18n/it";

/** Mostra il login finché non c'è una sessione (07 3); un 401 da qualunque chiamata riporta qui. */
export function AuthGate({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.isPending) {
    return (
      <main className="flex min-h-screen items-center justify-center" role="status">
        {strings.session.checking}
      </main>
    );
  }
  if (me.isError) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-space-12">
        <p role="alert">{strings.session.unavailable}</p>
        <Button onClick={() => void me.refetch()}>{strings.session.retry}</Button>
      </main>
    );
  }
  return me.data.authenticated ? <>{children}</> : <LoginPage />;
}
