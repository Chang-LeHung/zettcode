// The pictures a message carries. The page served by the gateway draws them from its own address; an app cannot put
// its token in an `<img>`, so it reads the bytes with a bearer and draws the blob instead.

import { apiUrl, authorization, connection } from "./connection";

/** The gateway's address for one picture of a thread. */
export function picturePath(thread: string, picture: string): string {
  return `/api/threads/${encodeURIComponent(thread)}/pictures/${encodeURIComponent(picture)}`;
}

/** A `src` for an `<img>`: the path in the page, or a blob URL read with the app's token. */
export async function pictureUrl(path: string): Promise<string> {
  if (!connection.baseUrl) return path;
  const response = await fetch(apiUrl(path), { credentials: "omit", headers: authorization() });
  if (!response.ok) throw new Error(`The picture did not load (${response.status})`);
  return URL.createObjectURL(await response.blob());
}
