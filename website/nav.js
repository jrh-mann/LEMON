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
  var prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function isElementInView(el, threshold) {
    var ratio = typeof threshold === 'number' ? threshold : 0.92;
    var rect = el.getBoundingClientRect();
    return rect.top < window.innerHeight * ratio;
  }

  function slugify(text) {
    return String(text || '')
      .toLowerCase()
      .replace(/[^a-z0-9\s-]/g, '')
      .trim()
      .replace(/\s+/g, '-')
      .replace(/-+/g, '-');
  }

  function observeOnce(target, onVisible, options) {
    if (prefersReducedMotion) {
      onVisible();
      return;
    }

    if (isElementInView(target, 0.94)) {
      onVisible();
      return;
    }

    if (typeof IntersectionObserver === 'undefined') {
      onVisible();
      return;
    }

    var observer;

    try {
      observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            onVisible();
            observer.unobserve(entry.target);
          }
        });
      }, options || { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
    } catch (error) {
      onVisible();
      return;
    }

    observer.observe(target);
  }

  function buildNav() {
    var nav = document.createElement('nav');
    nav.className = 'nav';

    var navInner = document.createElement('div');
    navInner.className = 'nav-inner';

    var brand = document.createElement('a');
    brand.className = 'nav-brand';
    brand.href = 'index.html';
    brand.textContent = 'LEMON';
    navInner.appendChild(brand);

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

    navInner.appendChild(navLinks);
    nav.appendChild(navInner);
    document.body.insertBefore(nav, document.body.firstChild);

    function updateNavOnScroll() {
      nav.classList.toggle('is-scrolled', window.scrollY > 8);
    }

    updateNavOnScroll();
    window.addEventListener('scroll', updateNavOnScroll, { passive: true });
  }

  function buildContentSections() {
    var container = document.querySelector('.container');
    if (!container) {
      return;
    }

    var children = Array.prototype.slice.call(container.children);
    var hasDirectH2 = children.some(function (child) {
      return child.tagName === 'H2';
    });

    if (!hasDirectH2) {
      return;
    }

    var currentSection = null;

    children.forEach(function (child) {
      if (child.tagName === 'H2') {
        currentSection = document.createElement('section');
        currentSection.className = 'content-section';
        container.insertBefore(currentSection, child);
        currentSection.appendChild(child);
        return;
      }

      if (currentSection) {
        currentSection.appendChild(child);
      }
    });
  }

  function setupPageIndexSpy(headings, linksById) {
    if (!headings.length) {
      return;
    }

    var currentActiveId = null;

    function setActive(id) {
      if (!id || id === currentActiveId || !linksById[id]) {
        return;
      }

      if (currentActiveId && linksById[currentActiveId]) {
        linksById[currentActiveId].classList.remove('is-active');
      }

      currentActiveId = id;
      linksById[currentActiveId].classList.add('is-active');
    }

    if (window.location.hash) {
      var hashId = window.location.hash.slice(1);
      if (linksById[hashId]) {
        setActive(hashId);
      }
    }

    if (typeof IntersectionObserver !== 'undefined') {
      try {
        var observer = new IntersectionObserver(function (entries) {
          entries.forEach(function (entry) {
            if (entry.isIntersecting) {
              setActive(entry.target.id);
            }
          });
        }, {
          threshold: 0.18,
          rootMargin: '-18% 0px -66% 0px'
        });

        headings.forEach(function (heading) {
          observer.observe(heading);
        });
      } catch (error) {
        // Ignore and rely on scroll fallback.
      }
    }

    function updateActiveByScroll() {
      var best = headings[0];
      for (var i = 0; i < headings.length; i += 1) {
        var heading = headings[i];
        if (heading.getBoundingClientRect().top <= 120) {
          best = heading;
        } else {
          break;
        }
      }
      if (best && best.id) {
        setActive(best.id);
      }
    }

    updateActiveByScroll();
    window.addEventListener('scroll', updateActiveByScroll, { passive: true });
  }

  function buildPageSidebar() {
    var container = document.querySelector('.container');
    if (!container) {
      return;
    }

    var headings = Array.prototype.slice.call(container.querySelectorAll('h2'));
    if (!headings.length) {
      return;
    }

    var idCounts = {};
    headings.forEach(function (heading, index) {
      if (!heading.id) {
        var base = slugify(heading.textContent) || ('section-' + (index + 1));
        var count = idCounts[base] || 0;
        idCounts[base] = count + 1;
        heading.id = count === 0 ? base : (base + '-' + (count + 1));
      }
    });

    var layout = document.createElement('div');
    layout.className = 'report-layout';

    container.parentNode.insertBefore(layout, container);

    var sidebar = document.createElement('aside');
    sidebar.className = 'page-sidebar';

    var header = document.createElement('div');
    header.className = 'page-sidebar-header';

    var title = document.createElement('div');
    title.className = 'page-sidebar-title';
    title.textContent = 'On this page';

    var subtitle = document.createElement('div');
    subtitle.className = 'page-sidebar-subtitle';
    subtitle.textContent = 'Jump to sections';

    header.appendChild(title);
    header.appendChild(subtitle);
    sidebar.appendChild(header);

    var list = document.createElement('ul');
    list.className = 'page-index';

    var linksById = {};
    headings.forEach(function (heading) {
      var item = document.createElement('li');
      var link = document.createElement('a');
      link.className = 'page-index-link';
      link.href = '#' + heading.id;
      link.textContent = heading.textContent.trim();
      link.addEventListener('click', function () {
        if (history && typeof history.replaceState === 'function') {
          history.replaceState(null, '', '#' + heading.id);
        }
      });

      item.appendChild(link);
      list.appendChild(item);
      linksById[heading.id] = link;
    });

    sidebar.appendChild(list);
    layout.appendChild(sidebar);
    layout.appendChild(container);
    document.body.classList.add('has-page-sidebar');

    setupPageIndexSpy(headings, linksById);
  }

  function setupHeroStagger() {
    var hero = document.querySelector('.hero');
    if (!hero) {
      return;
    }

    var items = Array.prototype.slice.call(hero.children);
    if (!items.length) {
      return;
    }

    hero.classList.add('hero-animated');
    items.forEach(function (item, index) {
      item.classList.add('stagger-item');
      item.style.setProperty('--stagger-index', String(index));
    });

    requestAnimationFrame(function () {
      hero.classList.add('is-visible');
    });
  }

  function setupSectionReveal() {
    document.body.classList.add('animations-ready');

    var targets = Array.prototype.slice.call(
      document.querySelectorAll('.container > section, .blog-entry')
    );

    if (!targets.length) {
      return;
    }

    try {
      var accentPalette = [
        'var(--color-accent)',
        'var(--color-accent-amber)',
        'var(--color-accent-green)',
        'var(--color-accent-purple)',
        'var(--color-accent-rose)'
      ];

      targets.forEach(function (target, index) {
        target.classList.add('reveal');
        target.style.setProperty('--reveal-delay', String((index % 4) * 24) + 'ms');
        target.style.setProperty('--section-accent', accentPalette[index % accentPalette.length]);

        observeOnce(target, function () {
          target.classList.add('is-visible');
        });
      });
    } catch (error) {
      targets.forEach(function (target) {
        target.classList.add('is-visible');
      });
    }

    window.setTimeout(function () {
      targets.forEach(function (target) {
        if (!target.classList.contains('is-visible')) {
          target.classList.add('is-visible');
        }
      });
    }, 1200);
  }

  function setupGanttAnimation() {
    var ganttContainer = document.querySelector('.gantt-container');
    if (!ganttContainer) {
      return;
    }

    var bars = Array.prototype.slice.call(
      ganttContainer.querySelectorAll('svg rect[height="24"]')
    );

    if (!bars.length) {
      return;
    }

    bars.forEach(function (bar) {
      bar.classList.add('gantt-bar');
    });

    observeOnce(ganttContainer, function () {
      ganttContainer.classList.add('gantt-animated');
      bars.forEach(function (bar, index) {
        bar.style.transitionDelay = String(index * 45) + 'ms';
        bar.classList.add('is-visible');
      });
    }, { threshold: 0.2, rootMargin: '0px 0px -10% 0px' });
  }

  function setupDiagramDraw() {
    var svgs = Array.prototype.slice.call(document.querySelectorAll('.diagram svg'));
    if (!svgs.length) {
      return;
    }

    svgs.forEach(function (svg) {
      svg.classList.add('draw-in');

      var drawables = Array.prototype.slice.call(
        svg.querySelectorAll('path, line, polyline, polygon')
      );

      drawables.forEach(function (shape) {
        var stroke = shape.getAttribute('stroke');
        if (!stroke || stroke === 'none' || typeof shape.getTotalLength !== 'function') {
          return;
        }

        try {
          var length = shape.getTotalLength();
          if (!isFinite(length) || length <= 0) {
            return;
          }

          shape.classList.add('drawable-path');
          shape.style.setProperty('--path-length', String(Math.ceil(length)));
        } catch (error) {
          // Some SVG elements can throw for getTotalLength in older browsers.
        }
      });

      observeOnce(svg, function () {
        svg.classList.add('is-drawn');
      }, { threshold: 0.2, rootMargin: '0px 0px -10% 0px' });
    });
  }

  function setupPrototypeGalleryReveal() {
    var gallery = document.querySelector('.prototype-gallery');
    if (!gallery) {
      return;
    }

    var figures = Array.prototype.slice.call(gallery.querySelectorAll('figure'));
    if (!figures.length) {
      return;
    }

    figures.forEach(function (figure, index) {
      figure.classList.add('gallery-reveal');
      figure.style.setProperty('--gallery-index', String(index));
    });

    gallery.classList.add('gallery-animate');

    observeOnce(gallery, function () {
      gallery.classList.add('is-visible');
    }, { threshold: 0.15, rootMargin: '0px 0px -6% 0px' });

    window.setTimeout(function () {
      if (!gallery.classList.contains('is-visible')) {
        gallery.classList.add('is-visible');
      }
    }, 1300);
  }

  function setupProgressBars() {
    var progressBlocks = Array.prototype.slice.call(
      document.querySelectorAll('.progress-overview')
    );

    if (!progressBlocks.length) {
      return;
    }

    progressBlocks.forEach(function (block) {
      var fills = Array.prototype.slice.call(
        block.querySelectorAll('.progress-fill[data-progress]')
      );

      fills.forEach(function (fill) {
        if (!prefersReducedMotion) {
          fill.style.width = '0%';
        }
      });

      observeOnce(block, function () {
        fills.forEach(function (fill, index) {
          var value = fill.getAttribute('data-progress') || '0';
          fill.style.transitionDelay = String(index * 50) + 'ms';
          fill.style.width = value + '%';
        });
      }, { threshold: 0.25, rootMargin: '0px 0px -10% 0px' });
    });
  }

  function findNearestHeadingText(element) {
    var current = element;
    while (current) {
      var sibling = current.previousElementSibling;
      while (sibling) {
        if (/^H[1-4]$/.test(sibling.tagName)) {
          return sibling.textContent.trim();
        }
        sibling = sibling.previousElementSibling;
      }
      current = current.parentElement;
    }
    return '';
  }

  function ensureLazyMediaAttributes() {
    var images = Array.prototype.slice.call(
      document.querySelectorAll('.screenshot, .diagram img, .prototype-gallery img')
    );

    images.forEach(function (image) {
      if (!image.hasAttribute('loading')) {
        image.setAttribute('loading', 'lazy');
      }
      if (!image.hasAttribute('decoding')) {
        image.setAttribute('decoding', 'async');
      }
    });

    var iframes = Array.prototype.slice.call(document.querySelectorAll('iframe'));
    iframes.forEach(function (iframe) {
      var src = iframe.getAttribute('src') || '';
      if (!iframe.hasAttribute('title')) {
        var headingText = findNearestHeadingText(iframe) || 'Embedded video';
        iframe.setAttribute('title', headingText + ' video');
      }
      iframe.setAttribute('loading', 'lazy');
      iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');

      if (/REPLACE_[A-Z_]+/.test(src)) {
        var placeholder = document.createElement('div');
        placeholder.className = 'video-placeholder';

        var title = document.createElement('p');
        title.textContent = 'Monthly video link pending';

        var note = document.createElement('p');
        note.className = 'embed-note';
        note.textContent = 'Replace this placeholder with a public YouTube or OneDrive link before submission.';

        placeholder.appendChild(title);
        placeholder.appendChild(note);
        iframe.replaceWith(placeholder);
      }
    });
  }

  function enhanceFigures() {
    var standaloneScreenshots = Array.prototype.slice.call(
      document.querySelectorAll('img.screenshot:not(figure img)')
    );

    standaloneScreenshots.forEach(function (image) {
      var figure = document.createElement('figure');
      figure.className = 'report-figure report-figure-auto';
      image.parentNode.insertBefore(figure, image);
      figure.appendChild(image);

      var caption = document.createElement('figcaption');
      caption.textContent = image.getAttribute('alt') || 'Screenshot';
      figure.appendChild(caption);
    });

    var captions = Array.prototype.slice.call(
      document.querySelectorAll('figure figcaption, .diagram .caption')
    );

    captions.forEach(function (caption, index) {
      caption.setAttribute('data-figure-number', String(index + 1));
    });
  }

  function buildBackToTop() {
    var button = document.createElement('button');
    button.className = 'back-to-top';
    button.type = 'button';
    button.setAttribute('aria-label', 'Back to top');
    button.innerHTML = '<span class="back-to-top-icon" aria-hidden="true">↑</span><span class="back-to-top-label">Back to top</span>';

    function updateButton() {
      button.classList.toggle('is-visible', window.scrollY > 520);
    }

    button.addEventListener('click', function () {
      window.scrollTo({
        top: 0,
        behavior: prefersReducedMotion ? 'auto' : 'smooth'
      });
    });

    updateButton();
    window.addEventListener('scroll', updateButton, { passive: true });
    document.body.appendChild(button);
  }

  function buildFooter() {
    var footer = document.createElement('footer');
    footer.className = 'footer';
    footer.textContent = 'LEMON · UCL COMP0016 Systems Engineering 2025/26 · Avanade & CloudSurge';
    document.body.appendChild(footer);
  }

  buildNav();
  buildContentSections();
  buildPageSidebar();
  setupHeroStagger();
  setupSectionReveal();
  setupGanttAnimation();
  setupDiagramDraw();
  setupPrototypeGalleryReveal();
  setupProgressBars();
  ensureLazyMediaAttributes();
  enhanceFigures();
  buildBackToTop();
  buildFooter();
})();
