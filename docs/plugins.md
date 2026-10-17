# Editor plugins

Plugins are trusted application code installed when building a custom image. They cannot be installed through the wiki interface. Static theme consumers do not load editor plugins.

`editor/plugins.js` exports `PLUGIN_API_VERSION` (currently `1`) and `registerPlugin(plugin)`. Registration returns an unregister function. Names must be unique identifiers starting with a letter.

| Field | Contract |
| --- | --- |
| `apiVersion` | Required: `1` |
| `name` | Required: unique Tiptap node name |
| `level` | Required: `inline` or `block` |
| `parse(source)` | Required: return `{raw, parameters}` matching a source prefix, or `undefined` |
| `serialize(attributes)` | Required: return source from `{source, parameters}` |
| `validate(parameters)` | Required: validate parsed or edited parameters |
| `label` | Human-readable node name |
| `start` | Markdown tokenizer start hint |
| `view(element, attributes)` | Populate visual node view; treat content as untrusted |
| `editable` | Enable double-click source editing with validation |
| `commands` | Tiptap command definitions |

Unknown HTML and shortcodes remain protected source nodes. Server-side validation still applies to publication.

See [`editor/plugins-example.js`](../editor/plugins-example.js). Register it in `editor/main.js` before initialization:

```js
import { installBadgePlugin } from './plugins-example.js';
installBadgePlugin();
```

Rebuild the browser bundle and image:

```sh
npm ci
npm run build
docker build -f runtime/Dockerfile -t my-wiki .
```

Include corresponding Hugo shortcodes or render hooks when emitting custom syntax. Registration adds editing support; Hugo owns published rendering. Version plugin code with the image and test parse/serialize round trips before deployment.
