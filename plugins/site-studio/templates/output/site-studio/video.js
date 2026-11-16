// site-studio video facade (site-fidelity 0.3.0, design section 7.3). A video block shows a poster and
// loads nothing from the video's host until the visitor clicks it; without this script the click simply
// follows the link to the video's own page. No dependency, no network request of its own.
(function () {
  document.addEventListener('click', function (event) {
    var link = event.target && event.target.closest && event.target.closest('a.ss-video');
    var src = link && link.getAttribute('data-embed');
    if (!src) return;
    event.preventDefault();
    var frame = document.createElement('iframe');
    frame.src = src + (src.indexOf('?') < 0 ? '?' : '&') + 'autoplay=1';
    frame.title = link.textContent || 'Video';
    frame.className = 'ss-video-frame';
    frame.allow = 'autoplay; fullscreen; picture-in-picture';
    frame.setAttribute('allowfullscreen', '');
    frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    link.parentNode.replaceChild(frame, link);
  });
})();
