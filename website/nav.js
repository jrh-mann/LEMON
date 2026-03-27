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

  function observeOnce(target, onVisible, options) {
    if (prefersReducedMotion) {
      onVisible();
      return;
    }

    if (isElementInView(target, 0.94)) {
      onVisible();
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          onVisible();
          observer.unobserve(entry.target);
        }
      });
    }, options || { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });

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

    targets.forEach(function (target, index) {
      target.classList.add('reveal');
      target.style.setProperty('--reveal-delay', String((index % 4) * 24) + 'ms');

      observeOnce(target, function () {
        target.classList.add('is-visible');
      });
    });
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

    observeOnce(gallery, function () {
      gallery.classList.add('is-visible');
    }, { threshold: 0.15, rootMargin: '0px 0px -6% 0px' });
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

  function buildFooter() {
    var footer = document.createElement('footer');
    footer.className = 'footer';
    footer.textContent = 'LEMON · UCL COMP0016 Systems Engineering 2025/26 · Avanade & CloudSurge';
    document.body.appendChild(footer);
  }

  buildNav();
  buildContentSections();
  setupHeroStagger();
  setupSectionReveal();
  setupGanttAnimation();
  setupDiagramDraw();
  setupPrototypeGalleryReveal();
  setupProgressBars();
  buildFooter();
})();
