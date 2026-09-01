/**
 * LinkedIn Discovery & Matcher Dashboard Controller
 * Vanilla JS - Fast, robust, responsive.
 */

document.addEventListener('DOMContentLoaded', () => {
  // State
  let currentTab = 'leads-tab';
  let activeEventSource = null;
  let cachedLeads = [];
  let cachedJobs = [];
  let crmData = [];
  let currentCrmFilter = 'all';

  // DOM Elements
  const modal = document.getElementById('detailModal');
  const btnClose = document.getElementById('btnCloseModal');

  // Navigation Titles
  const TAB_TITLES = {
    'leads-tab': {
      title: 'Leads & Directores B2B',
      subtitle: 'Encuentra tomadores de decisión y evalúa su afinidad según tu producto o criterios'
    },
    'jobs-tab': {
      title: 'Buscador de Empleo',
      subtitle: 'Calcula tu porcentaje de compatibilidad con ofertas de empleo según tus skills y experiencia'
    },
    'companies-tab': {
      title: 'Empresas & Señales Comerciales',
      subtitle: 'Analiza la presencia de empresas y detecta intención de compra o contratación en sus publicaciones'
    },
    'inspector-tab': {
      title: 'Inspector de Enlace Directo',
      subtitle: 'Pega cualquier URL de LinkedIn para extraer su ficha estructurada y porcentaje de match'
    },
    'crm-tab': {
      title: 'CRM / Leads Guardados',
      subtitle: 'Gestiona el estado de contacto, notas y seguimiento de tus prospectos'
    },
    'session-tab': {
      title: 'Estado de Sesión',
      subtitle: 'Comprueba y autentica tu cuenta de LinkedIn para mantener activo el scraping'
    }
  };

  // --- Initial Setup ---
  initTabs();
  checkSessionStatus();
  loadCRMLeads();
  loadTabLeads();
  loadTabJobs();
  initFormListeners();
  initModalListeners();

  // --- Tab Navigation ---
  function initTabs() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        if (!targetTab) return;

        navItems.forEach(n => n.classList.remove('active'));
        btn.classList.add('active');

        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
        const pane = document.getElementById(targetTab);
        if (pane) pane.classList.add('active');

        currentTab = targetTab;
        if (TAB_TITLES[targetTab]) {
          document.getElementById('currentTabTitle').textContent = TAB_TITLES[targetTab].title;
          document.getElementById('currentTabSubtitle').textContent = TAB_TITLES[targetTab].subtitle;
        }

        if (targetTab === 'leads-tab') {
          loadTabLeads();
        } else if (targetTab === 'jobs-tab') {
          loadTabJobs();
        } else if (targetTab === 'crm-tab') {
          loadCRMLeads();
        }
      });
    });
  }

  async function loadTabLeads() {
    try {
      const res = await fetch('/api/leads?item_type=person');
      const data = await res.json();
      if (data && data.length > 0) {
        const formatted = data.map(d => ({
          name: d.title,
          job_title: d.subtitle ? d.subtitle.split('@')[0].trim() : '',
          company: d.subtitle && d.subtitle.includes('@') ? d.subtitle.split('@')[1].trim() : '',
          location: d.location,
          score: d.score,
          score_breakdown: d.score_breakdown || {},
          linkedin_url: d.linkedin_url,
          about: d.raw_data?.about || '',
          experiences: d.raw_data?.experiences || [],
          icebreakers: d.raw_data?.icebreakers || [],
          contacts: d.raw_data?.contacts || []
        }));
        renderLeadsResults(formatted);
      }
    } catch (e) {
      console.error('Error loading tab leads:', e);
    }
  }

  async function loadTabJobs() {
    try {
      const res = await fetch('/api/leads?item_type=job');
      const data = await res.json();
      if (data && data.length > 0) {
        const formatted = data.map(d => ({
          job_title: d.title,
          company: d.subtitle,
          location: d.location,
          score: d.score,
          score_breakdown: d.score_breakdown || {},
          linkedin_url: d.linkedin_url,
          job_description: d.raw_data?.job_description || '',
          posted_date: d.raw_data?.posted_date || 'Reciente'
        }));
        renderJobsResults(formatted);
      }
    } catch (e) {
      console.error('Error loading tab jobs:', e);
    }
  }

  // --- Session Status ---
  async function checkSessionStatus() {
    try {
      const res = await fetch('/api/session/status');
      const data = await res.json();
      
      const indicator = document.getElementById('globalSessionIndicator');
      const dot = indicator.querySelector('.status-dot');
      const label = indicator.querySelector('.session-label');
      
      const badgeLg = document.getElementById('sessionBadgeLarge');
      const statusVal = document.getElementById('sessionStatusVal');
      const pathVal = document.getElementById('sessionPathVal');
      const cookiesVal = document.getElementById('sessionCookiesVal');
      const timeVal = document.getElementById('sessionTimeVal');

      if (data.exists && data.cookies_count > 0) {
        dot.className = 'status-dot active';
        label.textContent = `Sesión activa (${data.cookies_count} cookies)`;
        badgeLg.textContent = 'Activa';
        badgeLg.style.color = '#34d399';
        statusVal.textContent = 'Conectada y lista';
      } else {
        dot.className = 'status-dot error';
        label.textContent = 'Sesión requerida';
        badgeLg.textContent = 'No autenticado';
        badgeLg.style.color = '#f87171';
        statusVal.textContent = data.message || 'Sin sesión';
      }

      pathVal.textContent = data.path || '-';
      cookiesVal.textContent = data.cookies_count || '0';
      timeVal.textContent = data.last_modified || 'Nunca';
    } catch (e) {
      console.error('Error checking session:', e);
    }
  }

  document.getElementById('btnRefreshSession')?.addEventListener('click', checkSessionStatus);
  document.getElementById('btnCheckSessionNow')?.addEventListener('click', checkSessionStatus);

  document.getElementById('btnLaunchLogin')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnLaunchLogin');
    btn.disabled = true;
    btn.innerHTML = '<span>Abriendo navegador... Completa el login</span>';
    
    try {
      const res = await fetch('/api/session/login', { method: 'POST' });
      const data = await res.json();
      alert(data.message);
      await checkSessionStatus();
    } catch (e) {
      alert('Error al iniciar login: ' + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<span>Iniciar Sesión en Navegador (1 Clic)</span>';
    }
  });

  // --- Real-time Progress Streaming (SSE) ---
  function listenToTaskStream(taskId, onCompleteCallback, onItemReceivedCallback) {
    if (activeEventSource) {
      activeEventSource.close();
    }

    const banner = document.getElementById('taskBanner');
    const statusText = document.getElementById('taskStatusText');
    const pctText = document.getElementById('taskPct');
    const barFill = document.getElementById('progressBarFill');
    const btnStop = document.getElementById('btnStopTask');

    banner.style.display = 'block';
    barFill.style.width = '5%';
    statusText.textContent = 'Iniciando proceso...';
    pctText.textContent = '5%';

    // Setup Stop button
    if (btnStop) {
      btnStop.onclick = async () => {
        btnStop.textContent = '⏹ Deteniendo...';
        btnStop.disabled = true;
        try {
          await fetch(`/api/tasks/${taskId}/stop`, { method: 'POST' });
        } catch (e) {
          console.error(e);
        }
      };
      btnStop.textContent = '⏹ Detener';
      btnStop.disabled = false;
    }

    activeEventSource = new EventSource(`/api/tasks/${taskId}/events`);

    activeEventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const pct = data.percent || 0;
        
        statusText.textContent = data.message || 'Procesando...';
        pctText.textContent = `${pct}%`;
        barFill.style.width = `${pct}%`;

        // Handle single item stream (de 1 en 1)
        if (data.item && onItemReceivedCallback) {
          onItemReceivedCallback(data.item);
        }

        if (data.status === 'completado') {
          activeEventSource.close();
          setTimeout(() => {
            banner.style.display = 'none';
          }, 2500);
          if (onCompleteCallback && data.results) {
            onCompleteCallback(data.results);
          }
          loadCRMLeads();
        } else if (data.status === 'error') {
          activeEventSource.close();
          statusText.textContent = `Error: ${data.message}`;
          barFill.style.backgroundColor = '#ef4444';
          setTimeout(() => {
            banner.style.display = 'none';
            barFill.style.backgroundColor = 'var(--accent-primary)';
          }, 4000);
        }
      } catch (e) {
        console.error('Error parsing SSE event:', e);
      }
    };

    activeEventSource.onerror = () => {
      activeEventSource.close();
      setTimeout(() => {
        banner.style.display = 'none';
      }, 2000);
    };
  }

  // --- Form Handlers ---
  function initFormListeners() {
    // 1. Search Leads
    const formLeads = document.getElementById('formSearchLeads');
    formLeads?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btnSubmitLeads');
      btn.disabled = true;

      const payload = {
        title: document.getElementById('leadTitle').value.trim(),
        location: document.getElementById('leadLocation').value.trim(),
        limit: parseInt(document.getElementById('leadLimit').value, 10),
        target_roles: document.getElementById('leadTargetRoles').value.trim(),
        target_keywords: document.getElementById('leadKeywords').value.trim(),
        require_email: document.getElementById('leadRequireEmail') ? document.getElementById('leadRequireEmail').checked : false
      };

      // Reset live results list for fresh streaming
      cachedLeads = [];
      document.getElementById('leadsCardsContainer').innerHTML = '<div class="empty-state"><div class="pulse-indicator" style="margin: 0 auto 12px; width: 14px; height: 14px;"></div><h3>Buscando y calificando leads de 1 en 1...</h3><p>Los perfiles irán apareciendo aquí conforme se analicen.</p></div>';
      document.getElementById('leadsResultsCount').textContent = 'Buscando en LinkedIn...';

      try {
        const res = await fetch('/api/search/leads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.task_id) {
          listenToTaskStream(
            data.task_id,
            (finalResults) => {
              renderLeadsResults(finalResults || cachedLeads);
            },
            (singleLead) => {
              // Item received 1 by 1!
              cachedLeads.unshift(singleLead);
              renderLeadsResults(cachedLeads);
            }
          );
        }
      } catch (err) {
        alert('Error: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    });

    // 2. Search Jobs
    const formJobs = document.getElementById('formSearchJobs');
    formJobs?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btnSubmitJobs');
      btn.disabled = true;

      const payload = {
        keywords: document.getElementById('jobKeywords').value.trim(),
        location: document.getElementById('jobLocation').value.trim(),
        limit: parseInt(document.getElementById('jobLimit').value, 10),
        user_skills: document.getElementById('userSkills').value.trim(),
        desired_titles: document.getElementById('desiredJobTitles').value.trim(),
        remote_only: false
      };

      // Reset live results list for fresh streaming
      cachedJobs = [];
      document.getElementById('jobsCardsContainer').innerHTML = '<div class="empty-state"><div class="pulse-indicator" style="margin: 0 auto 12px; width: 14px; height: 14px;"></div><h3>Buscando y calculando compatibilidad de 1 en 1...</h3><p>Las ofertas irán apareciendo aquí en vivo.</p></div>';
      document.getElementById('jobsResultsCount').textContent = 'Buscando en LinkedIn...';

      try {
        const res = await fetch('/api/search/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.task_id) {
          listenToTaskStream(
            data.task_id,
            (finalResults) => {
              renderJobsResults(finalResults || cachedJobs);
            },
            (singleJob) => {
              // Item received 1 by 1!
              cachedJobs.unshift(singleJob);
              renderJobsResults(cachedJobs);
            }
          );
        }
      } catch (err) {
        alert('Error: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    });

    // 3. Analyze Company
    const formComp = document.getElementById('formAnalyzeCompany');
    formComp?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btnSubmitCompany');
      btn.disabled = true;

      const payload = {
        company_url: document.getElementById('companyUrlInput').value.trim(),
        include_posts: document.getElementById('chkIncludePosts').checked
      };

      try {
        const res = await fetch('/api/company/analyze', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.task_id) {
          listenToTaskStream(data.task_id, (results) => {
            renderCompanyResult(results[0]);
          });
        }
      } catch (err) {
        alert('Error: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    });

    // 4. Direct Inspector
    const formInspect = document.getElementById('formInspectUrl');
    formInspect?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = document.getElementById('btnSubmitInspect');
      btn.disabled = true;

      const payload = {
        url: document.getElementById('inspectUrlInput').value.trim()
      };

      try {
        const res = await fetch('/api/inspect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.task_id) {
          listenToTaskStream(data.task_id, (results) => {
            renderInspectResult(results[0]);
          });
        }
      } catch (err) {
        alert('Error: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    });

    // View Toggles (Cards / Table)
    document.querySelectorAll('.view-toggle button').forEach(b => {
      b.addEventListener('click', () => {
        document.querySelectorAll('.view-toggle button').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        const mode = b.getAttribute('data-view');
        const cardsCont = document.getElementById('leadsCardsContainer');
        const tableCont = document.getElementById('leadsTableWrapper');
        if (mode === 'table') {
          cardsCont.style.display = 'none';
          tableCont.style.display = 'block';
        } else {
          cardsCont.style.display = 'grid';
          tableCont.style.display = 'none';
        }
      });
    });
  }

  // --- Render Functions ---
  function getScoreBadgeClass(score) {
    if (score >= 75) return 'high';
    if (score >= 45) return 'medium';
    return 'low';
  }

  function renderLeadsResults(leads) {
    cachedLeads = leads;
    const countEl = document.getElementById('leadsResultsCount');
    countEl.textContent = `${leads.length} leads procesados y calificados`;

    const cardsContainer = document.getElementById('leadsCardsContainer');
    const tableBody = document.getElementById('leadsTableBody');

    if (!leads || leads.length === 0) {
      cardsContainer.innerHTML = '<div class="empty-state"><h3>No se encontraron perfiles</h3><p>Prueba con otros términos de búsqueda o verifica que la sesión de LinkedIn esté activa.</p></div>';
      tableBody.innerHTML = '';
      return;
    }

    // Cards
    cardsContainer.innerHTML = leads.map((lead, i) => {
      const score = lead.score || 0;
      const badgeCls = getScoreBadgeClass(score);
      const matchedKws = lead.score_breakdown?.matched_keywords || [];
      const notes = lead.score_breakdown?.notes || [];

      return `
        <div class="lead-card">
          <div class="card-top">
            <div class="card-identity">
              <h4>${escapeHtml(lead.name || 'Sin nombre')}</h4>
              <div class="card-subtitle">${escapeHtml(lead.job_title || '')} ${lead.company ? `@ ${escapeHtml(lead.company)}` : ''}</div>
              <div class="card-location">${escapeHtml(lead.location || 'Ubicación no especificada')}</div>
            </div>
            <div class="score-pill ${badgeCls}">${score}%</div>
          </div>

          ${matchedKws.length > 0 ? `
            <div class="card-tags">
              ${matchedKws.map(k => `<span class="tag-badge matched">✓ ${escapeHtml(k)}</span>`).join('')}
            </div>
          ` : ''}

          ${notes.length > 0 ? `
            <div class="card-notes">${escapeHtml(notes[0])}</div>
          ` : ''}

          <div class="card-actions">
            <div class="card-btn-group">
              <button class="btn btn-secondary btn-sm" onclick="openDetailModal('lead', ${i})">Ver Detalle</button>
              <button class="btn btn-secondary btn-sm" onclick="openIcebreakerModal(${i})">💬 Mensaje</button>
            </div>
            <a href="${lead.linkedin_url}" target="_blank" rel="noreferrer" class="btn btn-secondary btn-sm">LinkedIn ↗</a>
          </div>
        </div>
      `;
    }).join('');

    // Table
    tableBody.innerHTML = leads.map((lead, i) => {
      const score = lead.score || 0;
      const badgeCls = getScoreBadgeClass(score);
      const matchedKws = lead.score_breakdown?.matched_keywords || [];

      return `
        <tr>
          <td><span class="score-pill ${badgeCls}">${score}%</span></td>
          <td><strong>${escapeHtml(lead.name || '')}</strong><br><small style="color:var(--text-muted)">${escapeHtml(lead.job_title || '')}</small></td>
          <td>${escapeHtml(lead.company || '-')}</td>
          <td>${escapeHtml(lead.location || '-')}</td>
          <td>${matchedKws.slice(0, 2).map(k => `<span class="tag-badge matched">${escapeHtml(k)}</span>`).join(' ') || '-'}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="openDetailModal('lead', ${i})">Ficha</button>
            <a href="${lead.linkedin_url}" target="_blank" class="btn btn-secondary btn-sm">↗</a>
          </td>
        </tr>
      `;
    }).join('');
  }

  function renderJobsResults(jobs) {
    cachedJobs = jobs;
    const countEl = document.getElementById('jobsResultsCount');
    countEl.textContent = `${jobs.length} ofertas analizadas con % Match`;

    const container = document.getElementById('jobsCardsContainer');
    if (!jobs || jobs.length === 0) {
      container.innerHTML = '<div class="empty-state"><h3>No se encontraron ofertas de empleo</h3><p>Prueba ampliando la ubicación o los términos.</p></div>';
      return;
    }

    container.innerHTML = jobs.map((job, i) => {
      const score = job.score || 0;
      const badgeCls = getScoreBadgeClass(score);
      const matchedSkills = job.score_breakdown?.matched_skills || [];
      const descPreview = job.job_description ? job.job_description.slice(0, 180) + '...' : 'Sin descripción';

      return `
        <div class="lead-card">
          <div class="card-top">
            <div class="card-identity">
              <h4>${escapeHtml(job.job_title || 'Puesto')}</h4>
              <div class="card-subtitle">${escapeHtml(job.company || 'Empresa confidencial')}</div>
              <div class="card-location">📍 ${escapeHtml(job.location || 'No especificada')} • ${escapeHtml(job.posted_date || 'Reciente')}</div>
            </div>
            <div class="score-pill ${badgeCls}">${score}% Match</div>
          </div>

          ${matchedSkills.length > 0 ? `
            <div class="card-tags">
              ${matchedSkills.map(s => `<span class="tag-badge matched">✓ ${escapeHtml(s)}</span>`).join('')}
            </div>
          ` : ''}

          <div class="card-notes">${escapeHtml(descPreview)}</div>

          <div class="card-actions">
            <button class="btn btn-secondary btn-sm" onclick="openJobModal(${i})">Ver Requisitos & Match</button>
            <a href="${job.linkedin_url}" target="_blank" rel="noreferrer" class="btn btn-primary btn-sm">Postular en LinkedIn ↗</a>
          </div>
        </div>
      `;
    }).join('');
  }

  window.openJobModal = (index) => {
    const job = cachedJobs[index];
    if (!job) return;

    const modalScore = document.getElementById('modalScoreBadge');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');

    const score = job.score || 0;
    modalScore.textContent = `${score}% Match de Empleo`;
    modalScore.className = `score-pill ${getScoreBadgeClass(score)}`;
    modalTitle.textContent = job.job_title || 'Detalle de Oferta';

    const breakdown = job.score_breakdown || {};
    const matchedSkills = breakdown.matched_skills || [];
    const missingSkills = breakdown.missing_skills || [];

    modalBody.innerHTML = `
      <div>
        <h4 style="font-size: 16px; font-weight: 600; color: var(--text-primary);">${escapeHtml(job.job_title || '')}</h4>
        <p style="color: #93c5fd; font-size: 13px;">${escapeHtml(job.company || 'Empresa confidencial')}</p>
        <p style="color: var(--text-muted); font-size: 12px; margin-top: 2px;">📍 ${escapeHtml(job.location || 'No especificada')} • Publicado: ${escapeHtml(job.posted_date || 'Reciente')}</p>
      </div>

      <div class="score-breakdown-box">
        <h4 class="modal-section-title">Compatibilidad con tu Perfil</h4>
        
        <div class="breakdown-row">
          <span>Alineación de Cargo</span>
          <div class="breakdown-bar"><div class="breakdown-bar-fill" style="width: ${breakdown.title_score || 0}%"></div></div>
          <span>${breakdown.title_score || 0}%</span>
        </div>

        <div class="breakdown-row">
          <span>Habilidades Técnicas</span>
          <div class="breakdown-bar"><div class="breakdown-bar-fill" style="width: ${breakdown.skills_score || 0}%"></div></div>
          <span>${breakdown.skills_score || 0}%</span>
        </div>

        <div class="breakdown-row">
          <span>Ubicación / Modalidad</span>
          <div class="breakdown-bar"><div class="breakdown-bar-fill" style="width: ${breakdown.location_score || 0}%"></div></div>
          <span>${breakdown.location_score || 0}%</span>
        </div>
      </div>

      ${matchedSkills.length > 0 ? `
        <div>
          <h4 class="modal-section-title">Habilidades Coincidentes (${matchedSkills.length})</h4>
          <div class="card-tags">
            ${matchedSkills.map(s => `<span class="tag-badge matched">✓ ${escapeHtml(s)}</span>`).join('')}
          </div>
        </div>
      ` : ''}

      ${missingSkills.length > 0 ? `
        <div>
          <h4 class="modal-section-title" style="color:#f87171">Habilidades No Detectadas en tu Búsqueda (${missingSkills.length})</h4>
          <div class="card-tags">
            ${missingSkills.map(s => `<span class="tag-badge" style="border-color:rgba(239,68,68,0.3); color:#fca5a5;">✕ ${escapeHtml(s)}</span>`).join('')}
          </div>
        </div>
      ` : ''}

      ${job.job_description ? `
        <div>
          <h4 class="modal-section-title">Descripción del Puesto</h4>
          <div style="font-size: 13px; color: var(--text-secondary); line-height: 1.6; white-space: pre-line; max-height: 250px; overflow-y: auto; background: #0d121f; padding: 12px; border-radius: var(--radius-sm);">
            ${escapeHtml(job.job_description)}
          </div>
        </div>
      ` : ''}

      <div>
        <a href="${job.linkedin_url}" target="_blank" rel="noreferrer" class="btn btn-primary">Abrir Oferta en LinkedIn ↗</a>
      </div>
    `;

    modal.style.display = 'flex';
  };

  function renderCompanyResult(company) {
    const container = document.getElementById('companyResultContainer');
    if (!company) {
      container.innerHTML = '<div class="empty-state"><h3>No se pudo obtener información de la empresa</h3></div>';
      return;
    }

    const score = company.score || 0;
    const badgeCls = getScoreBadgeClass(score);
    const signals = company.signals || [];
    const posts = company.posts || [];

    container.innerHTML = `
      <div class="card">
        <div class="card-top" style="margin-bottom: 16px;">
          <div>
            <h3 style="font-size: 18px; font-weight: 700;">${escapeHtml(company.name || 'Empresa')}</h3>
            <div class="card-subtitle">${escapeHtml(company.industry || '')} • ${escapeHtml(company.company_size || '')}</div>
            <div class="card-location">Sede: ${escapeHtml(company.headquarters || 'No especificada')} • Web: <a href="${company.website}" target="_blank" style="color:#60a5fa">${escapeHtml(company.website || '-')}</a></div>
          </div>
          <div class="score-pill ${badgeCls}">${score}% Señal Comercial</div>
        </div>

        ${company.about_us ? `
          <div style="margin-bottom: 18px; color: var(--text-secondary); line-height: 1.5; font-size: 13px;">
            <strong>Acerca de:</strong> ${escapeHtml(company.about_us)}
          </div>
        ` : ''}

        <h4 class="modal-section-title">Señales de Compra y Crecimiento Detectadas (${signals.length})</h4>
        <div style="display: flex; flex-direction: column; gap: 8px; margin-bottom: 20px;">
          ${signals.length > 0 ? signals.map(s => `
            <div class="card-notes" style="border-left-color: #34d399;">
              <strong style="color: #a7f3d0;">${escapeHtml(s.category)}:</strong> "${escapeHtml(s.quote)}"
            </div>
          `).join('') : '<div style="color:var(--text-muted); font-size:12px;">No se detectaron publicaciones con triggers explícitos recientes.</div>'}
        </div>

        ${posts.length > 0 ? `
          <h4 class="modal-section-title">Publicaciones Recientes Analizadas (${posts.length})</h4>
          <div class="cards-grid">
            ${posts.map(p => `
              <div class="lead-card" style="padding: 12px;">
                <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">📅 ${escapeHtml(p.posted_date || 'Fecha N/A')} • 👍 ${p.reactions_count || 0} • 💬 ${p.comments_count || 0}</div>
                <div style="font-size: 12px; color: var(--text-primary); line-height: 1.4;">${escapeHtml(p.text ? p.text.slice(0, 200) + '...' : 'Sin texto')}</div>
                ${p.linkedin_url ? `<a href="${p.linkedin_url}" target="_blank" style="font-size: 11px; color: #60a5fa; margin-top: 6px; display: inline-block;">Ver post ↗</a>` : ''}
              </div>
            `).join('')}
          </div>
        ` : ''}
      </div>
    `;
  }

  function renderInspectResult(data) {
    const container = document.getElementById('inspectResultContainer');
    if (!data) return;

    const score = data.score || 0;
    const badgeCls = getScoreBadgeClass(score);

    container.innerHTML = `
      <div class="card">
        <div class="card-top" style="margin-bottom: 14px;">
          <div>
            <h3>${escapeHtml(data.name || data.job_title || data.title || 'Elemento')}</h3>
            <div class="card-subtitle">${escapeHtml(data.company || data.industry || data.subtitle || '')}</div>
            <div class="card-location">${escapeHtml(data.location || '')}</div>
          </div>
          <div class="score-pill ${badgeCls}">${score}% Match</div>
        </div>

        <div style="margin-top: 14px;">
          <a href="${data.linkedin_url}" target="_blank" class="btn btn-primary btn-sm">Abrir en LinkedIn ↗</a>
        </div>
      </div>
    `;
  }

  // --- CRM Leads ---
  async function loadCRMLeads() {
    try {
      const res = await fetch('/api/leads');
      crmData = await res.json();

      document.getElementById('crmCount').textContent = crmData.length;
      document.getElementById('crmTotalPill').textContent = crmData.length;

      renderCRMTable();
    } catch (e) {
      console.error('Error loading CRM leads:', e);
    }
  }

  document.querySelectorAll('.filter-pill').forEach(pill => {
    pill.addEventListener('click', () => {
      document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
      pill.classList.add('active');
      currentCrmFilter = pill.getAttribute('data-crm-filter');
      renderCRMTable();
    });
  });

  function renderCRMTable() {
    const tableBody = document.getElementById('crmTableBody');
    let filtered = crmData;

    if (currentCrmFilter !== 'all') {
      filtered = crmData.filter(d => d.crm_status === currentCrmFilter);
    }

    if (!filtered || filtered.length === 0) {
      tableBody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding:32px; color:var(--text-muted);">No hay leads en este estado. Realiza búsquedas para guardar automáticamente.</td></tr>';
      return;
    }

    tableBody.innerHTML = filtered.map(lead => {
      const score = lead.score || 0;
      const badgeCls = getScoreBadgeClass(score);
      const statuses = ['Nuevo', 'Contactado', 'En seguimiento', 'Interesado', 'Descartado'];

      return `
        <tr>
          <td><span class="score-pill ${badgeCls}">${score}%</span></td>
          <td><span class="tag-badge">${lead.item_type || 'lead'}</span></td>
          <td><strong>${escapeHtml(lead.title || '')}</strong></td>
          <td>${escapeHtml(lead.subtitle || '-')}</td>
          <td>
            <select class="form-select" style="padding: 4px 8px; font-size: 11px;" onchange="updateLeadStatus(${lead.id}, this.value)">
              ${statuses.map(st => `<option value="${st}" ${lead.crm_status === st ? 'selected' : ''}>${st}</option>`).join('')}
            </select>
          </td>
          <td>
            <input type="text" class="form-input" style="padding: 4px 8px; font-size: 12px;" value="${escapeHtml(lead.notes || '')}" placeholder="Agregar nota..." onblur="updateLeadNote(${lead.id}, this.value)" />
          </td>
          <td>
            <a href="${lead.linkedin_url}" target="_blank" class="btn btn-secondary btn-sm">↗</a>
            <button class="btn btn-secondary btn-sm" style="color:#f87171" onclick="deleteLeadItem(${lead.id})">✕</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  document.getElementById('btnReloadCRM')?.addEventListener('click', loadCRMLeads);

  // CRM Global Actions (Exposed to window)
  window.updateLeadStatus = async (id, status) => {
    await fetch(`/api/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ crm_status: status })
    });
    loadCRMLeads();
  };

  window.updateLeadNote = async (id, note) => {
    await fetch(`/api/leads/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ notes: note })
    });
  };

  window.deleteLeadItem = async (id) => {
    if (confirm('¿Eliminar este registro del CRM?')) {
      await fetch(`/api/leads/${id}`, { method: 'DELETE' });
      loadCRMLeads();
    }
  };

  // --- Modal Logic ---
  function initModalListeners() {
    btnClose?.addEventListener('click', () => {
      modal.style.display = 'none';
    });
    modal?.addEventListener('click', (e) => {
      if (e.target === modal) modal.style.display = 'none';
    });
  }

  window.openDetailModal = (type, index) => {
    const lead = cachedLeads[index];
    if (!lead) return;

    const modalScore = document.getElementById('modalScoreBadge');
    const modalTitle = document.getElementById('modalTitle');
    const modalBody = document.getElementById('modalBody');

    const score = lead.score || 0;
    modalScore.textContent = `${score}% Lead Fit`;
    modalScore.className = `score-pill ${getScoreBadgeClass(score)}`;
    modalTitle.textContent = lead.name || 'Detalle del Lead';

    const breakdown = lead.score_breakdown || {};
    const experiences = lead.experiences || [];
    const educations = lead.educations || [];

    modalBody.innerHTML = `
      <div>
        <h4 style="font-size: 16px; font-weight: 600; color: var(--text-primary);">${escapeHtml(lead.name || '')}</h4>
        <p style="color: #93c5fd; font-size: 13px;">${escapeHtml(lead.job_title || '')} ${lead.company ? `@ ${escapeHtml(lead.company)}` : ''}</p>
        <p style="color: var(--text-muted); font-size: 12px; margin-top: 2px;">📍 ${escapeHtml(lead.location || 'No especificada')}</p>
      </div>

      <div class="score-breakdown-box">
        <h4 class="modal-section-title">Desglose del % de Afinidad</h4>
        
        <div class="breakdown-row">
          <span>Cargo & Rol</span>
          <div class="breakdown-bar"><div class="breakdown-bar-fill" style="width: ${breakdown.title_score || 0}%"></div></div>
          <span>${breakdown.title_score || 0}%</span>
        </div>

        <div class="breakdown-row">
          <span>Poder de Decisión (Seniority)</span>
          <div class="breakdown-bar"><div class="breakdown-bar-fill" style="width: ${breakdown.seniority_score || 0}%"></div></div>
          <span>${breakdown.seniority_score || 0}%</span>
        </div>

        <div class="breakdown-row">
          <span>Palabras Clave & Producto</span>
          <div class="breakdown-bar"><div class="breakdown-bar-fill" style="width: ${breakdown.keywords_score || 0}%"></div></div>
          <span>${breakdown.keywords_score || 0}%</span>
        </div>

        <div class="breakdown-row">
          <span>Ubicación</span>
          <div class="breakdown-bar"><div class="breakdown-bar-fill" style="width: ${breakdown.location_score || 0}%"></div></div>
          <span>${breakdown.location_score || 0}%</span>
        </div>
      </div>

      ${lead.about ? `
        <div>
          <h4 class="modal-section-title">Resumen / Acerca de</h4>
          <p style="font-size: 13px; color: var(--text-secondary); line-height: 1.5;">${escapeHtml(lead.about)}</p>
        </div>
      ` : ''}

      ${lead.contacts && lead.contacts.length > 0 ? `
        <div>
          <h4 class="modal-section-title" style="color: #34d399;">📬 Información de Contacto</h4>
          <div style="display:flex; flex-direction:column; gap:8px;">
            ${lead.contacts.map(c => `
              <div style="background: rgba(52, 211, 153, 0.1); border: 1px solid rgba(52, 211, 153, 0.3); border-radius: 6px; padding: 8px;">
                <span style="font-size: 11px; text-transform: uppercase; color: #34d399; font-weight: bold;">${escapeHtml(c.type || 'Otro')}</span><br/>
                <a href="${c.url || 'javascript:void(0)'}" target="_blank" style="color: var(--text-primary); font-size: 13px; word-break: break-all;">${escapeHtml(c.value || c.url || '')}</a>
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}

      ${lead.icebreakers && lead.icebreakers.length > 0 ? `
        <div>
          <h4 class="modal-section-title">Mensaje de Contacto Sugerido (Icebreaker)</h4>
          <div class="icebreaker-box">
            <p class="icebreaker-text" id="icebreakerText">${escapeHtml(lead.icebreakers[0])}</p>
            <button class="btn btn-secondary btn-sm btn-copy-icebreaker" onclick="copyIcebreaker()">Copiar Mensaje</button>
          </div>
        </div>
      ` : ''}

      ${experiences.length > 0 ? `
        <div>
          <h4 class="modal-section-title">Experiencia Laboral (${experiences.length})</h4>
          <div style="display:flex; flex-direction:column; gap:8px;">
            ${experiences.slice(0, 4).map(exp => `
              <div style="border-left: 2px solid var(--border-color); padding-left: 10px;">
                <div style="font-weight: 600; color: var(--text-primary); font-size: 13px;">${escapeHtml(exp.position_title || '')}</div>
                <div style="color: var(--text-secondary); font-size: 12px;">${escapeHtml(exp.institution_name || '')} • ${escapeHtml(exp.from_date || '')} - ${escapeHtml(exp.to_date || 'Presente')}</div>
              </div>
            `).join('')}
          </div>
        </div>
      ` : ''}

      <div>
        <a href="${lead.linkedin_url}" target="_blank" rel="noreferrer" class="btn btn-primary">Abrir Perfil Completo en LinkedIn ↗</a>
      </div>
    `;

    modal.style.display = 'flex';
  };

  window.openIcebreakerModal = (index) => {
    window.openDetailModal('lead', index);
  };

  window.copyIcebreaker = () => {
    const text = document.getElementById('icebreakerText')?.textContent;
    if (text) {
      navigator.clipboard.writeText(text);
      alert('Mensaje copiado al portapapeles.');
    }
  };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
});
