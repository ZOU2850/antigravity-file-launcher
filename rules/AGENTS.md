# File Launcher Rules

When completing a task that creates, modifies, or outputs local files (such as `.pptx`, `.docx`, `.xlsx`, `.pdf`, `.html`, `.md`, images, archives, or code files):

1. **Structured Final File Presentation**:
   At the end of your response, present a clean, concise **产出的文件 (Output Files)** summary listing each final deliverable with a clickable `file:///` Markdown link (using forward slashes on Windows, e.g. `[report.pptx](file:///D:/projects/demo/report.pptx)`).
2. **Surface the File Launcher Pill**:
   Whenever one or more deliverable files are produced or when the user asks to open/view files with external applications ("Open With", system default app, or File Explorer), include the UI plugin pill on its own line so the user can one-click open the **File Launcher** side panel:
   `[File Launcher](sidecar://file-launcher/launcher_pane/)`
