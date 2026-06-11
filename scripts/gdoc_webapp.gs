/**
 * Google Apps Script web app that turns posted HTML into a Google Doc in your
 * Drive and returns its URL. Used by the blogpost studio's "→ Google Doc"
 * button (src/blogpost_studio_web.py, gdoc endpoint).
 *
 * One-time setup (~3 minutes):
 *   1. Go to https://script.google.com → New project, paste this file.
 *   2. Left sidebar → Services (+) → add "Drive API" (Advanced Drive Service).
 *   3. Deploy → New deployment → type "Web app":
 *        - Execute as: Me
 *        - Who has access: Anyone
 *      Authorize when prompted.
 *   4. Copy the web app URL (https://script.google.com/macros/s/…/exec) into
 *      slopbench/.env as:  GDOC_WEBAPP_URL=<that url>
 *
 * The URL is a capability: anyone who has it can create docs in your Drive,
 * so treat it like a secret (it lives only in .env, which is not committed).
 */
function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var blob = Utilities.newBlob(data.html, "text/html", (data.title || "writeup") + ".html");
  var file = Drive.Files.create(
    { name: data.title || "writeup", mimeType: "application/vnd.google-apps.document" },
    blob
  );
  // Anyone with the link can comment — easy to ship around for feedback.
  DriveApp.getFileById(file.id).setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.COMMENT);
  return ContentService.createTextOutput(
    JSON.stringify({ url: "https://docs.google.com/document/d/" + file.id + "/edit" })
  ).setMimeType(ContentService.MimeType.JSON);
}
