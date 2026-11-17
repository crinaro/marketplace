# The site-studio content model (reference)

<!-- GENERATED from the tables in scripts/content.py, scripts/siteconfig.py and scripts/build.py. Do not edit by hand: the plugin's maintainers regenerate it, and their tests fail when it and the code disagree. -->

What your site's files may hold, and what the build reads. This page is written from the build's own tables, so it names exactly the keys, tokens, blocks and settings this version knows. Where this page and the build disagree, the build is right, and that is a bug in the plugin to report. A site is schema 1, 2 or 3 (this version reads up to 3); the plugin writes the lowest schema that holds your site, and nothing here changes a site that does not use it.

## Where things live

| what | where | notes |
| --- | --- | --- |
| site settings | `site/site.json` | written only by the plugin; keys below |
| a piece of work | `content/<portfolio>/<piece>/index.md` | front matter and a Markdown body. A piece is ONE page |
| a piece's files | `content/<portfolio>/<piece>/media/` | published as they are; nothing else in a piece folder is published |
| a portfolio | `content/<portfolio>/page.md` | one folder, one portfolio; the folder `work` needs no `page.md`. A folder or piece name starting with `_` is kept as source and never built |
| reserved names | `media`, `resume`, `references`, `about`, `home` | never a portfolio's folder name |
| home and about | `content/home.md`, `content/about.md` | at schema 3 also `content/home/index.md` and `content/about/index.md`, each with its own `media/` |
| shared media | `content/media/` | published as they are |
| the resume | `content/resume/resume.md` | its PDF is `content/resume/resume.pdf` unless `site.json` says otherwise |
| a reference | `content/references/<name>/` | `reference.json`, `text.md` (never published) and a `card` image (`jpg`, `jpeg`, `png`, `webp`); only the card of a reference a page uses is published |
| your own pages | `site/src/` | copied as written, with tokens expanded |
| the layout | `site/templates/layout.html` | wraps every generated page |

## site.json

Top-level keys, in the order the plugin writes them. A key marked schema 2 makes a schema-1 file refused.

| key | schema | meaning |
| --- | --- | --- |
| `schema` | 1 | which reading of the tree this site uses (1, 2 or 3); the plugin writes the lowest one that holds the site. |
| `engine` | 1 | the marker that says this file is site-studio's; written for you. |
| `name` | 1 | your name, as printed on the site. |
| `siteTitle` | 1 | the site's title, used in page titles. |
| `siteKind` | 2 | `portfolio` (the default, never written), `hub` or `custom`: what `site/src` and `content/` hold. Values: `portfolio`, `hub`, `custom`. |
| `publicRepo` | 1 | the public GitHub repository the site is published to, as `owner/name`. |
| `previewUrl` | 1 | the public address of the preview, an https URL; share tags and the sitemap need it. |
| `domain` | 1 | your own domain, once the site is on it. |
| `cutover` | 1 | true to use `domain` as the site's address instead of `previewUrl` (needs `domain`). |
| `publicEmails` | 1 | the e-mail addresses the site is allowed to print. |
| `privateTerms` | 1 | words the site must never publish; the checks look for them. |
| `work` | 1 | the default portfolio's settings (see Portfolio settings). |
| `featuredFrom` | 2 | `home` (the featured list in `content/home.md`) or `flags` (each piece's own `featured: true`). Values: `home`, `flags`. |
| `redirects` | 1 | old address to new page, one redirect page each. |
| `resume` | 1 | the resume's source and PDF, or null for none (keys below). |
| `budgets` | 1 | overrides for the performance limits (keys below). |

`resume` holds `path`, `pdf`, `paper`; `paper` is one of `Letter`, `A4`.

| resume key | meaning |
| --- | --- |
| `path` | the resume's Markdown source (default `content/resume/resume.md`). |
| `pdf` | the resume's PDF (default `content/resume/resume.pdf`), or null for no PDF. |
| `paper` | `Letter` or `A4`; required when the resume has a PDF. |

`budgets` holds any of these, each with its default:

| budget | default | meaning |
| --- | --- | --- |
| `firstViewMaxMB` | 1.5 | first-view images per page, at 2x, in MB. |
| `pageImagesMaxMB` | 5 | all images per page, at 2x, in MB. |
| `sizeCopyOverKB` | 250 | an image over this many KB needs size copies. |
| `treeMaxMB` | 200 | the whole published tree, in MB. |

## Portfolio settings

The same keys are set in `site.json` `work` (the default portfolio) and in a portfolio's `page.md` front matter, which overrides them. Any other key is refused.

| key | meaning |
| --- | --- |
| `label` | the portfolio's name in the menu and on its index. |
| `description` | the portfolio's meta description. |
| `required` | front matter keys every piece must have; a piece without one is refused. |
| `meta` | piece keys printed as a list on each piece's page, in this order. |
| `cardMeta` | piece keys printed on each piece's card. |
| `groupBy` | a piece key whose value groups the cards; `groups` names the allowed values. |
| `groups` | the allowed values of the `groupBy` key, in display order. |
| `labels` | display names: `labels.meta` for `meta` keys, `labels.groups` for group names (schema 2). |

Portfolio page keys (a `page.md`, schema 3): each is refused below schema 3 with `needs "schema": 3`.

| key | values | default | meaning |
| --- | --- | --- | --- |
| `order` | see meaning | none | menu order: a whole number; portfolios with one come first, ascending. |
| `tagline` | see meaning | none | one line printed under the portfolio index's title. |
| `sort` | `date`, `order` | `date` | how pieces are ordered: `date` (newest first) or `order` (a piece's own whole-number `order` first). |
| `menuLinks` | `index`, `single-piece` | `index` | `index` (the menu links the portfolio's index) or `single-piece` (links the piece when only one is built). |
| `view` | `grid`, `page` | `grid` | `grid` (the generated index) or `page` (your own `site/src/<portfolio>/index.html`). |

## Page front matter

Home, about, resume and portfolio pages read a fixed set of keys; any other key is refused.

| page | keys |
| --- | --- |
| home (`content/home.md`) | `title`, `description`, `featured`, `feed`, `endorsement`, `photo`, `photoAlt`, `contact` |
| about (`content/about.md`) | `title`, `description`, `endorsement`, `photo`, `photoAlt`, `contact` |
| resume (`content/resume/resume.md`) | `title`, `description` (and `contact` at schema 3) |
| portfolio (`page.md`) | `title`, `label`, `description`, `required`, `meta`, `cardMeta`, `groupBy`, `groups`, `labels`, `order`, `tagline`, `sort`, `menuLinks`, `view` |

| key | meaning |
| --- | --- |
| `title` | the page's title. |
| `description` | the page's meta description. |
| `featured` | the pieces to feature, as `portfolio/piece` names, in order (not used under `featuredFrom: flags`). |
| `feed` | reference names shown as the `Elsewhere` cards. |
| `endorsement` | a map with `quote` and, optionally, `by`. |
| `photo` | a published image in the page's media folder; `photoAlt` is then required. |
| `photoAlt` | the photo's alternative text (required with `photo`). |
| `contact` | a map of label to value, printed on the page. |
| `order` | menu order: a whole number; portfolios with one come first, ascending. |
| `tagline` | one line printed under the portfolio index's title. |
| `sort` | how pieces are ordered: `date` (newest first) or `order` (a piece's own whole-number `order` first). |
| `menuLinks` | `index` (the menu links the portfolio's index) or `single-piece` (links the piece when only one is built). |
| `view` | `grid` (the generated index) or `page` (your own `site/src/<portfolio>/index.html`). |

## A piece's front matter

`title` is required. A piece also reads the group key (`groupBy`) and every key its portfolio's `meta` or `cardMeta` lists. **A key that is none of these is not published.** The build still builds the site and prints a warning naming the file, the key and the fix: add the key to `meta` or `cardMeta`, or remove it.

| key | meaning |
| --- | --- |
| `shortTitle` | a shorter title for cards and the menu. |
| `teaser` | one line printed on the card. |
| `coverPosition` | a CSS position for the cover, such as `center 30%`. |
| `cover` | the card's image: `media/<file>` in this piece's folder, or `ref:<name>`. |
| `order` | the piece's place when its portfolio sorts by `order`. |
| `title` | required; the piece's heading and card title. |
| `date` | `YYYY-MM-DD`; pieces sort newest first. |
| `draft` | `true` keeps the piece out of a publish build (a preview shows it). |
| `description` | the page's meta description (default: the teaser, then an excerpt). |
| `featured` | `true` features the piece (read only under `featuredFrom: flags`). |

A `meta` or `cardMeta` list that names a built-in key (`shortTitle`, `teaser`, `coverPosition`, `cover`, `order`, `title`, `date`, `draft`) is refused at schema 3, because the build shows it already.

**A piece is one page.** In a piece folder, a `.md` file other than `index.md`, and a sub-folder other than `media/`, are not published. The build names each one in a warning, and says: pieces have one page; put this in index.md, or start the name with _ to keep it as source. A name starting with `_` is the way to keep something there as source.

## References

`reference.json` holds these keys; `url` and `title` are required.

| key | meaning |
| --- | --- |
| `url` | the page's address (required). |
| `title` | the page's title (required). |
| `description` | a short description. |
| `site` | the site's name. |
| `published` | the publication date. |
| `kind` | what sort of page it is. |
| `captured` | when it was captured. |

## Layout tokens

A token is `{{name}}` or `{{name:argument}}`, in a page under `site/src` or in the layout (each scope below says where it is read). **An unknown token is refused**, naming the file and line; it is never printed as text. To show braces as text, write `&#123;&#123;`.

- **value**: a text value, in every file the build expands tokens in.
  - `{{siteUrl}}`: the site's address.
  - `{{siteTitle}}`: `siteTitle` from `site.json`.
  - `{{name}}`: `name` from `site.json`.
  - `{{year}}`: the year of the newest commit touching `site/` or `content/` (never the clock).
  - `{{root}}`: the relative path back to the site's root.
- **nav**: the site navigation, in every file the build expands tokens in.
  - `{{nav}}`: the menu.
- **link**: the address of a built page, as `{{link:work}}` or `{{link:work/piece}}`; a page that is not built is refused.
  - `{{link:<page>}}`: a link to a built page.
- **featured**: the featured cards, in `site/src` pages and the layout only (never a Markdown body).
  - `{{featured}}`: the featured selection as cards (a portfolio site only).
- **home**: one part of `content/home.md`, as `{{home:title}}`; `site/src` pages only (schema 3).
  - `{{home:<part>}}`: a part of the home page's copy.
- **layout**: a value only `site/templates/layout.html` receives.
  - `{{title}}`: the page's title.
  - `{{pageTitle}}`: the page's title with the site's.
  - `{{description}}`: the page's meta description.
  - `{{content}}`: the page's body.

`{{#page:X}}...{{/page}}` prints its block only when page X is built, and nothing otherwise (schema 2).

## Markdown

Headings (a `#` is printed as h2: the page title is the h1), paragraphs, one level of `-`/`*` and `1.` lists, `>` quotes, `---`, `**bold**`, `*em*`, `` `code` ``, links and images. Raw HTML is escaped. A link must be http(s), mailto, an in-page `#anchor` or relative: a root-absolute link is refused, because the same site is served at `/<repo>/` and at `/`. A line holding only a YouTube, Vimeo or public Drive link is an embed; `ref: <name>` lines print reference cards.

At schema 3 these blocks are read (a block opens with `:::name` and closes with a line holding only `:::`); below schema 3 the same lines are text:

| block | write |
| --- | --- |
| `:::tiles` | one row per tile, `figure \| label`. |
| `:::quote` | the words, then optionally a last line `-- Name, Role, *Title*`. |
| `:::gallery` | image lines only. |
| `:::videos` | rows `title \| url` or `title \| url \| media/poster.jpg` (YouTube, Vimeo or a public Drive link). |
| `:::carousel` | blocks, or `###` headings that each start a slide. |
| `:::part` | `:::part <name>`: a named part of the home page, read by `{{home:<name>}}`. |

A part name may not be one of `title`, `description`, `intro`, `photo`, `endorsement`, `feed`, `contact`.

| line form | meaning |
| --- | --- |
| container | a line that opens a block: `:::name`. |
| leaf | a `::name` line: refused (this Markdown has no leaf directives). |
| close | a line holding only `:::` closes a block. |
| titled-image | an image line whose address is followed by a title in quotes prints that title as a caption. |

To show a block line as text, put a backslash in front of it, as `\:::tiles`.

## Images and size copies

A published image is `.jpg`, `.jpeg`, `.png`, `.gif`, `.webp`. A resized copy sits beside its original, and the build builds a `srcset` from the copies.

| naming | meaning |
| --- | --- |
| `.wNNN` | `<stem>.w<width><ext>` beside its original (schema 3); `<stem>-<width>w.<ext>` is read at every schema. |

Text files the build reads as text: `.html`, `.htm`, `.css`, `.js`, `.mjs`, `.json`, `.md`, `.txt`, `.xml`, `.svg`, `.webmanifest`.
