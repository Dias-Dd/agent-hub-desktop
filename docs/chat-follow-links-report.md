# Chat follow and compact webpage messages

Chat readers now track follow intent through delayed layout/content/image changes. Readers at the bottom follow updates; scrolling upward retains the reading position. Page messages render a text link and open the existing viewer on demand, with no inline iframe preview. Image previews remain available.

Validation: real Edge regression checks for late layout growth, preserved upward reading position, compact link and viewer interaction passed. Manager layout at 1440x900, 1024x600 and 600x800, reading preservation, agent panel, and demo artifact filtering passed. Packaged executable smoke: ok=true, assets=10, native_available=true.

Primary and desktop-build source synchronized; three executable copies updated. Active service frontend assets verified and updated without stopping model processes. Existing window needs a refresh to load new JavaScript. This build also includes the prior browser route query/fragment fix; that backend change requires restarting the application to activate.
