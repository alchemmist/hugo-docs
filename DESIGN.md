# Documentation design

Mode: Read. This is an extension of the user's existing documentation and blog
visual systems, not a replacement identity.

Pure white, ink #171717, link blue #173ea5, secondary ink #666666, dividers #e5e5e5.
No cards, gradients, decorative shadows or dashboard statistics. Navigation uses
the configured local monospace family, with JetBrains Mono as the generic fallback.
Socrat uses the exact CourierCyr regular, bold, italic and bold italic faces from
the blog for navigation and controls only. Long-form content uses Computer Modern
Roman. Inline and fenced code use Computer Modern Typewriter, independently of
the interface font. Reuse hugo-content's blog metrics: prose 18px desktop / 16px
at 650px and below; code 0.96em desktop / 0.85em mobile, line height 1.2, including
syntax tokens. Keep the module's inline code padding and backgrounds and fenced
code padding, rather than introducing a second documentation-specific code style.

A 264px left rail contains the existing blog logo, search, and a nested page tree.
The brand contains only the round logo and alchemmist, centered as one group
within the desktop sidebar. There is no sidebar footer. The desktop sidebar starts
16px from the top and reaches the viewport's bottom edge. Search has a compact
16px gap below the brand. The navigation mask fades at the actual bottom edge,
without a reserved white footer; the mobile drawer also reaches that edge.
The reading column is capped at 680px. A quiet 176px right rail contains the current
page outline. On wide screens the reading axis is centered; on narrow screens the
outline collapses into the page and navigation opens as a mobile drawer.

Titles are serif, 30px desktop and 26px mobile. Prose matches the live blog in both languages: Computer Modern Roman, 18px desktop / 16px mobile, normal line height,
and black text.
Heading fragment marks match the blog: Computer Modern Typewriter (independent
of the configured navigation/code font), 1.4em, weight 300, ink at 0.3 opacity.
Hover uses 0.7 opacity, scale 1.1 and the blog's subtle blue text glow. Keep the
native fragment links and smooth scrolling; desktop targets align to the viewport
top, while mobile uses one 80px offset to clear its sticky header, not two offsets.
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

Account management lives on the full `/admin` page; login lives on `/login`.
Both inherit the site's fonts, language and white/ink palette. Use serif headings,
monospace form controls, a quiet site link and a centered content column. Account,
Git status and user management are ordinary page sections, never modal panels.

Sections are folders, never document pages. Their entire row toggles the child
list. Only notes and the home overview have URLs, search results, and pager links.
Folder names in breadcrumbs are plain text.
