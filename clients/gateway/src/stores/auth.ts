// Whether this browser is signed in. The gateway can start agents that run commands, so nothing else is drawn until it is.

import { reactive } from "vue";
import { gateway } from "../api/gateway";
import { ApiError, onUnauthorized } from "../api/http";
import { disconnectServer, servers } from "./servers";

/** `open` is a gateway with no token: nobody signs in, so there is nothing to sign out of either. `readOnly` is a
 * sign-in with the read token: the gateway refuses every change, so the page says so instead of failing on each one. */
export const auth = reactive({ checked: false, signedIn: false, open: false, readOnly: false });

onUnauthorized(() => {
  auth.signedIn = false;
  if (servers.mode === "app") servers.problem = "The server refused the token; it may have been changed";
});

export async function checkSession(): Promise<void> {
  if (servers.mode === "app" && !servers.active) {
    auth.signedIn = false;
    auth.checked = true;
    return;
  }
  try {
    const session = await gateway.session();
    if (servers.mode === "app" && session.open === true) {
      // An app origin cannot write to an open gateway; an old profile may still point at one.
      auth.signedIn = false;
      servers.problem = "This gateway has no token; start it with --token to use the app";
      auth.checked = true;
      return;
    }
    auth.signedIn = session.authenticated;
    auth.open = session.open === true;
    auth.readOnly = session.role === "read";
    if (session.authenticated) servers.problem = "";
  } catch (failure) {
    auth.signedIn = false;
    if (servers.mode === "app" && !servers.problem) {
      servers.problem = failure instanceof ApiError ? failure.message : String(failure);
    }
  }
  auth.checked = true;
}

/** Sign in with the token. Throws an ApiError the form shows. */
export async function signIn(token: string): Promise<void> {
  const answer = await gateway.login(token.trim());
  auth.signedIn = answer.authenticated;
  auth.readOnly = answer.role === "read";
}

export async function signOut(): Promise<void> {
  if (servers.mode === "app") {
    await disconnectServer();
    return;
  }
  try {
    await gateway.logout();
  } finally {
    auth.signedIn = false;
  }
}
