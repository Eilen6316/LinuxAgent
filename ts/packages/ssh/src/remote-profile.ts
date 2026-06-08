export interface RemoteProfile {
  name: string;
  host: string;
  port: number;
  username: string;
  keyPath: string;
  knownHostsPath: string;
  allowedWorkdirs: string[];
  sudoPolicy: "none" | "allowlisted";
}

export function validateRemoteProfile(profile: RemoteProfile): RemoteProfile {
  if (!profile.name.trim()) throw new Error("remote profile name is required");
  if (!profile.host.trim()) throw new Error("remote profile host is required");
  if (!Number.isInteger(profile.port) || profile.port < 1 || profile.port > 65535) {
    throw new Error("remote profile port must be 1-65535");
  }
  if (!profile.username.trim()) throw new Error("remote profile username is required");
  if (!profile.keyPath.startsWith("/")) throw new Error("remote key path must be absolute");
  if (!profile.knownHostsPath.startsWith("/")) {
    throw new Error("known hosts path must be absolute");
  }
  if (profile.allowedWorkdirs.some((path) => !path.startsWith("/"))) {
    throw new Error("remote workdirs must be absolute");
  }
  if (profile.sudoPolicy !== "none" && profile.sudoPolicy !== "allowlisted") {
    throw new Error("remote sudo policy is invalid");
  }
  return profile;
}
