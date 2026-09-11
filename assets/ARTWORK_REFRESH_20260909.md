# Artwork refresh — 2026-09-09

Generated with the built-in OpenAI ImageGen tool, using existing application artwork as references. No game archive resources were accessed. This record describes provenance, not a new grant of third-party rights.

Production assets:
- `icons/app_icon.png`: simplified existing mascot, headphones and baton; charcoal background. The generated checkerboard draft was rejected and corrected with ImageGen.
- `icons/app_icon.ico`: format conversion of the final PNG, with 16/24/32/48/64/128/256 pixel Windows sizes.
- `ui/home/home_moonlit_atelier_v3.png`: moonlit atelier, retaining the previous character reference and right-side composition. The existing UI gradients and responsive crop remain in application code. The previous v2 background is retained as an unused source reference.

## Current style revision: Japanese anime / medieval adventure

At the user's request, both production PNGs were redrawn with the built-in
ImageGen tool using the preceding generated assets as style-transfer targets.
The production paths stay unchanged. The current icon uses bold outlines and
cel shadows; the home depicts a timber-built adventurer inn, travel gear and a
composing musician. The ICO was regenerated from the revised PNG. The sculpted
icon and palace scene are superseded; the earlier prompt set below records the
first pass, not the current style.

### Current icon prompt

Style-transfer edit. Redraw this app icon as authentic hand-drawn Japanese 2D fantasy adventure anime key art. Retain the same friendly black spirit silhouette, coral red eyes, ivory forehead curl, large headphones and conductor baton, same centered composition. BOLD confident dark ink outlines, expressive irregular line weight, large simple flat color shapes, only two-tone hard-edged cel shadows. Headphones mustard-gold with ivory highlights, charcoal mascot with indigo shadow planes. Energetic appealing graphic drawing, NOT a 3D render. Eliminate ALL metallic photoreal reflections, bevels, grain, leather pores, smooth shading, glow, bloom, tiny detail and plastic toy appearance. Flat muted slate blue background filling the entire square edge to edge; no rounded tile, no checkerboard, no transparency. No text, mockup or watermark. Readable at 32 pixels. One final square icon.

### Current home prompt

Style-transfer and scene redesign for music app homepage background, wide 16:9. Replace photoreal AI-render aesthetic completely with lovingly hand-drawn Japanese 2D medieval fantasy adventure anime: clearly visible confident ink contours with varied line weight, simplified expressive anime face, angular grouped hair locks, precise hands, flat cel colors and two-step crisp shadows, restrained hand-painted gouache backgrounds. NOT 3D, NOT photorealistic, NOT diffuse airbrush. Preserve white-haired musician character, gold hair bow, ivory and mustard-yellow clothes and black-gold wing accessory. Composition: character remains on RIGHT at 72% canvas width, head and hands within rightmost 40%, composing with a quill at a modest old oak table, small wooden keyboard instrument at right. Change overly luxurious Gothic palace to a lived-in medieval adventurer guild inn attic music corner: timber beams, simple stone wall, a travel satchel and folded map beside the lute, modest arched window on right looking onto distant castle and green foothills under dusky blue sky. Focused quiet moment preparing music before an adventure. Clear visual storytelling with a few deliberately drawn objects, no heaps of decorative clutter, no intricate gold filigree. LEFT 55% remains low-contrast shadowed slate-blue wall and timber architecture behind app controls; continuous natural scene, no black void or split panel. Warm amber lantern and muted blue ambient colors, restrained saturation, avoid magical sparkles, bokeh and volumetric glow. Strong line-art visible at normal app size. No text, readable notation, watermark, logo or UI. Final full-bleed illustration.

### Current revision validation

Home-page and packaging resource tests passed. Offscreen home rendering at
1440x900 and minimum size, all seven ICO sizes, and repository hygiene were
checked again. No UI logic or packaging paths changed in this style revision.

## Initial integration validation

- Full regression: 1,394 tests completed, OK, 12 skipped.
- Offscreen home rendering checked at 1440x900 and the supported minimum window size.
- All seven ICO sizes loaded successfully through Qt.
- Syntax, repository hygiene and whitespace checks passed.
- The executable was not rebuilt; changes apply to source launches and the next build.

## Final prompt set

### Icon

Use case: logo-brand. Redesign the referenced desktop music-composer app icon as a finished square 1024x1024 icon asset. Preserve recognizable friendly charcoal spirit mascot with red eyes, ivory forehead curl mark and headphones, but greatly simplify the visual. One bold large head silhouette, two readable soft coral eyes, oversized ivory/gold headphone arc, one tiny gold conductor baton on left. Remove staff lines, equalizer, separate note and all tiny floating specks. Refined softly sculpted enamel, restrained warm champagne-gold rim light on matte charcoal. Flat dark charcoal rounded-square tile fills almost all canvas, truly transparent outside rounded corners. Strong readable silhouette at 32 px, icon fills frame with 8% safe margin. Front view, symmetrical balance, premium and friendly. No text, no lettering, no watermark, no mockup, no multiple icons. Return final production image.

### Icon correction

Edit this icon only at the background: remove ALL checkerboard pattern around the rounded tile and replace those corner and border areas with continuous solid charcoal #18191b, matching the tile so the entire square is full-bleed charcoal. No transparency, no checkerboard, no white pixels in outer corners, no extra margin. Preserve the mascot, headphones, baton and their existing appearance and placement exactly. Final square app icon production PNG.

### Homepage

Use case: stylized-concept. Redesign this music composition app homepage illustration, final wide 16:9 landscape asset preferably 2048x1152. Preserve the reference white-haired musician's identity, gold bow, yellow and ivory costume and black-gold wing accessories. A more elegant airy painterly-cinematic fantasy composer atelier at blue hour, dark charcoal stone architecture, soft cool moonlit tall window and gentle warm champagne lantern light. She sits composing at a wooden desk with quill in right hand and her left hand resting naturally on a small keyboard instrument, lute nearby. Keep her head, hands and keyboard entirely within x=63%-89%, y=25%-78%, so responsive crops preserve them. Whole figure modestly sized, environment tells the story. Left 55% is continuous natural shadowed studio architecture with low detail and restrained contrast, suitable for application text and project list overlay; NOT solid black, no artificial split or panel. Far right window softly reveals distant fantasy rooftops and mountains. Better separation of character from background, less clutter and less brown than reference, tactile brushed illustration finish, anatomically credible hands, clean instrument geometry. Ivory-gold highlights coordinate with charcoal music app icon. No text, logos, watermarks, readable notation, UI controls or borders. Final full-bleed illustration, no mockup.
