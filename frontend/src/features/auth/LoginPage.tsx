import { useState, type FormEvent } from "react";
import { ApiError, NETWORK_ERROR_CODE } from "@/api/errors";
import { useLogin } from "@/api/queries";
import { useApi } from "@/api/provider";
import { Button } from "@/components/Button";
import { strings } from "@/i18n/it";

function messageFor(error: unknown): string {
  if (!(error instanceof ApiError)) return strings.login.generic;
  if (error.code === NETWORK_ERROR_CODE) return strings.login.network;
  switch (error.status) {
    case 401:
      return strings.login.wrongPassword;
    case 429:
      return strings.login.rateLimited(error.retryAfterSeconds);
    case 503:
      return strings.login.notConfigured;
    default:
      return strings.login.generic;
  }
}

/** La pagina di login (07 3): un campo password. Lo stile è provvisorio fino a F4-08. */
export function LoginPage() {
  const api = useApi();
  const login = useLogin();
  const [password, setPassword] = useState("");
  const [empty, setEmpty] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    const missing = password === "";
    setEmpty(missing);
    if (!missing) login.mutate(password);
  }

  const error = empty
    ? strings.login.emptyPassword
    : login.isError
      ? messageFor(login.error)
      : null;

  return (
    <main className="flex min-h-screen items-center justify-center p-layout-screen-padding">
      <form
        onSubmit={submit}
        noValidate
        className="w-full max-w-sm space-y-4 rounded-card border-hairline border-border-strong bg-surface-card p-space-24 text-text-primary"
      >
        <h1 className="text-xl">{strings.appName}</h1>
        <h2 className="text-sm text-text-secondary">{strings.login.title}</h2>
        {api.mode === "mock" && (
          <p className="text-sm text-text-secondary" role="note">
            {strings.mockNotice}
          </p>
        )}
        <div className="space-y-1">
          <label htmlFor="password" className="text-xs">
            {strings.login.passwordLabel}
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            aria-invalid={error !== null}
            aria-describedby={error ? "login-error" : undefined}
            className="h-size-control-height w-full rounded-control border-control border-border-strong bg-surface-nested px-space-12 text-sm"
          />
        </div>
        {error && (
          <p id="login-error" role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <Button type="submit" block loading={login.isPending}>
          {login.isPending ? strings.login.submitting : strings.login.submit}
        </Button>
      </form>
    </main>
  );
}
