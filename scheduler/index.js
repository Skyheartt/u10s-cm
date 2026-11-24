const DISPATCH_URL =
  "https://api.github.com/repos/Skyheartt/u10s-cm/actions/workflows/refresh.yml/dispatches";

export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(startRefresh(env));
  },
};

async function startRefresh(env) {
  const token = env.GITHUB_DISPATCH_TOKEN;
  if (!token) {
    console.log("GITHUB_DISPATCH_TOKEN is not set");
    return;
  }
  const response = await fetch(DISPATCH_URL, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "Content-Type": "application/json",
      "User-Agent": "u10s-cm-clock",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  console.log(`GitHub dispatch status ${response.status}`);
}
