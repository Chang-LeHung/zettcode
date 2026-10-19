/** Images the build inlines into the bundle as data URLs, so the page loads nothing from outside it. */
declare module "*.svg" {
  const url: string;
  export default url;
}
