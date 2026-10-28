// Whether this browser is signed in. The gateway can start agents that run commands, so nothing else is drawn until it is.

import { reactive } from "vue";
import { gateway } from "../api/gateway";
import { onUnauthorized } from "../api/http";

/** `open` is a gateway with no token: nobody signs in, so there is nothing to sign out of either. */
export const auth = reactive({ checked: false, signedIn: false, open: false });

onUnauthorized(() => {
  auth.signedIn = false;
});

export async function checkSession(): Promise<void> {
  try {
    const session = await gateway.session();
    auth.signedIn = session.authenticated;
    auth.open = session.open === true;
  } catch {
    auth.signedIn = false;
  }
  auth.checked = true;
}

/** Sign in with the token. Throws an ApiError the form shows. */
export async function signIn(token: string): Promise<void> {
  auth.signedIn = (await gateway.login(token.trim())).authenticated;
}

export async function signOut(): Promise<void> {
  try {
    await gateway.logout();
  } finally {
    auth.signedIn = false;
  }
}
