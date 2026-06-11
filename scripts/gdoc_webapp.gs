/**
 * Google Apps Script web app behind the blogpost studio's "→ Google Doc"
 * button (src/blogpost_studio_web.py, gdoc endpoint).
 *
 * Receives a .docx (base64) and maintains ONE Google Doc per project inside a
 * single "Research Projects" Drive folder:
 *   - folder missing  -> created
 *   - doc missing     -> created from the docx (named after the project)
 *   - doc exists      -> content REPLACED in place (same URL forever, full
 *                        revision history under File → Version history)
 * The .docx import path is Google's highest-fidelity conversion: embedded
 * figures and formatting survive (an HTML route drops data-URI images).
 *
 * One-time setup (~3 minutes):
 *   1. Go to https://script.google.com → New project, paste this file.
 *   2. Left sidebar → Services (+) → add "Drive API" (Advanced Drive Service)
 *      AND "Docs API" (used to flip the docs to pageless mode).
 *   3. Deploy → New deployment → type "Web app":
 *        - Execute as: Me
 *        - Who has access: Anyone
 *      Authorize when prompted.
 *   4. Copy the web app URL (https://script.google.com/macros/s/…/exec) into
 *      slopbench/.env as:  GDOC_WEBAPP_URL=<that url>
 *
 * To update an existing deployment after editing this code: Deploy → Manage
 * deployments → ✎ → Version: "New version" → Deploy (the URL stays the same).
 *
 * The URL is a capability: anyone who has it can write docs in your Drive,
 * so treat it like a secret (it lives only in .env, which is not committed).
 */
var FOLDER_NAME = "Research Projects";

function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var title = data.title || "writeup";
  var blob = Utilities.newBlob(
    Utilities.base64Decode(data.docx),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    title + ".docx"
  );

  // Find-or-create the shared folder.
  var folders = DriveApp.getFoldersByName(FOLDER_NAME);
  var folder = folders.hasNext() ? folders.next() : DriveApp.createFolder(FOLDER_NAME);

  // Find-or-create the project's doc inside it; re-exports replace content
  // in place so the URL is stable and history is kept.
  var existing = folder.getFilesByName(title);
  var fileId;
  if (existing.hasNext()) {
    fileId = existing.next().getId();
    Drive.Files.update({}, fileId, blob);
  } else {
    var file = Drive.Files.create(
      {
        name: title,
        mimeType: "application/vnd.google-apps.document",
        parents: [folder.getId()],
      },
      blob
    );
    fileId = file.id;
    // Anyone with the link can comment — easy to ship around for feedback.
    DriveApp.getFileById(fileId).setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.COMMENT);
  }

  // Pageless mode (idempotent — re-applied on every export).
  try {
    Docs.Documents.batchUpdate(
      {
        requests: [
          {
            updateDocumentStyle: {
              documentStyle: { documentFormat: { documentMode: "PAGELESS" } },
              fields: "documentFormat",
            },
          },
        ],
      },
      fileId
    );
  } catch (err) {
    // Non-fatal: the doc still exists, just paged. Surface in the response.
    return ContentService.createTextOutput(
      JSON.stringify({
        url: "https://docs.google.com/document/d/" + fileId + "/edit",
        folder: folder.getUrl(),
        warning: "pageless failed: " + err,
      })
    ).setMimeType(ContentService.MimeType.JSON);
  }

  return ContentService.createTextOutput(
    JSON.stringify({
      url: "https://docs.google.com/document/d/" + fileId + "/edit",
      folder: folder.getUrl(),
    })
  ).setMimeType(ContentService.MimeType.JSON);
}
