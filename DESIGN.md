# Documentation design

Mode: Read. This is an extension of the user's existing documentation and blog
visual systems, not a replacement identity.

Pure white, ink #171717, link blue #173ea5, secondary ink #666666, dividers #e5e5e5.
No cards, gradients, decorative shadows or dashboard statistics. Navigation uses
local JetBrains Mono. Long-form content uses the module's Computer Modern fonts.

A 264px left rail contains the existing blog logo, search, and a nested page tree.
The brand contains only the round logo and alchemmist, centered as one group
within the desktop sidebar. There is no sidebar footer.
The reading column is capped at 680px. A quiet 176px right rail contains the current
page outline. On wide screens the reading axis is centered; on narrow screens the
outline collapses into the page and navigation opens as a mobile drawer.

Titles are serif, 30px desktop and 26px mobile. Prose matches the live blog in both languages: Computer Modern Roman, 18px desktop / 16px mobile, normal line height,
and black text.
Controls are 13px monospace. The sidebar follows the supplied Diplodoc reference:
compact 32px rows, disclosure arrows before labels, and 20px nested indentation.
Sections start collapsed except the current page's ancestor branch; explicit user
choices persist. The current row uses one quiet neutral fill with regular text.
No sidebar link underlines, hover colors, button highlights, or tree guide lines.
Keyboard focus remains visible with an ink outline. Blue is reserved for links
outside the sidebar.

Search uses a native dialog with a generated local index. Every visible link leads
to a real page or section. Authored demo text is identified as such on the homepage.

Outer screen gutters are 8px left / 24px right on desktop and 10px left / 20px
right on mobile, without an overall layout width cap. The right outline aligns
with the right screen gutter.

Do not include back-to-top buttons or links anywhere in the documentation.

Sections are folders, never document pages. Their entire row toggles the child
list. Only notes and the home overview have URLs, search results, and pager links.
Folder names in breadcrumbs are plain text.
