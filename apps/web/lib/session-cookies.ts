/**
 * Session cookie names, isolated so edge middleware can read them without
 * importing the Node-only session module.
 */
export const ACCESS_COOKIE = "ag_access";
export const REFRESH_COOKIE = "ag_refresh";
export const ACTIVE_WORKSPACE_COOKIE = "ag_workspace";

export const SESSION_COOKIES = [ACCESS_COOKIE, REFRESH_COOKIE, ACTIVE_WORKSPACE_COOKIE] as const;
