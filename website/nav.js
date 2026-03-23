(function () {
  var pages = [
    { href: 'index.html', label: 'Home' },
    { href: 'requirements.html', label: 'Requirements' },
    { href: 'research.html', label: 'Research' },
    { href: 'algorithms.html', label: 'Algorithms' },
    { href: 'ui-design.html', label: 'UI Design' },
    { href: 'system-design.html', label: 'System Design' },
    { href: 'implementation.html', label: 'Implementation' },
    { href: 'testing.html', label: 'Testing' },
    { href: 'evaluation.html', label: 'Evaluation' },
    { href: 'conclusion.html', label: 'Conclusion' },
    { href: 'appendices.html', label: 'Appendices' },
    { href: 'blog.html', label: 'Blog' },
  ];

  var pathname = window.location.pathname;
  var segments = pathname.split('/');
  var currentPage = segments[segments.length - 1] || 'index.html';

  // Build nav
  var nav = document.createElement('nav');
  nav.className = 'nav';

  var brand = document.createElement('a');
  brand.className = 'nav-brand';
  brand.href = 'index.html';
  brand.textContent = 'LEMON';
  nav.appendChild(brand);

  var navLinks = document.createElement('div');
  navLinks.className = 'nav-links';

  pages.forEach(function (page) {
    var link = document.createElement('a');
    link.href = page.href;
    link.textContent = page.label;
    if (page.href === currentPage) {
      link.className = 'active';
    }
    navLinks.appendChild(link);
  });

  nav.appendChild(navLinks);
  document.body.insertBefore(nav, document.body.firstChild);

  // Build footer
  var footer = document.createElement('footer');
  footer.className = 'footer';
  footer.textContent = 'LEMON \u00b7 UCL COMP0016 Systems Engineering 2025/26 \u00b7 Avanade & CloudSurge';
  document.body.appendChild(footer);
})();
