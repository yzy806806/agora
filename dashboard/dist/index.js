// Agora Dashboard — Projects + Team + Profiles
// Uses Hermes Plugin SDK (React + UI components exposed on window)
(function () {
  const SDK = window.__HERMES_PLUGIN_SDK__;
  const REGISTRY = window.__HERMES_PLUGINS__;

  if (!SDK || !REGISTRY) {
    console.error("Hermes Plugin SDK not found");
    return;
  }

  const { React, hooks, components, utils, fetchJSON } = SDK;
  const { useState, useEffect, useCallback, useMemo, useRef } = hooks;
  const {
    Card, CardHeader, CardTitle, CardContent,
    Badge, Button, Checkbox, Input, Label,
    Select, SelectOption, Separator,
    Tabs, TabsList, TabsTrigger,
  } = components;
  const { cn, timeAgo, isoTimeAgo } = utils;

  const API = "/api/plugins/agora";

  // ========================================================================
  // API helpers
  // ========================================================================

  async function apiGet(path) {
    return fetchJSON(API + path);
  }

  async function apiPost(path, body) {
    return fetchJSON(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async function apiPut(path, body) {
    return fetchJSON(API + path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  }

  async function apiDelete(path) {
    return fetchJSON(API + path, { method: "DELETE" });
  }

  // ========================================================================
  // UI helper functions — reduce repetitive React.createElement patterns
  // ========================================================================

  // Card wrapper: card(title, children...) or card(title, { props }, children...)
  function card(title, children) {
    var props = {};
    if (children && !Array.isArray(children) && typeof children === "object" && !children.$$typeof) {
      props = children;
      children = Array.prototype.slice.call(arguments, 2);
    } else {
      children = Array.prototype.slice.call(arguments, 1);
    }
    return React.createElement(Card, props,
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, title),
      ),
      React.createElement(CardContent, null, children),
    );
  }

  // Colored badge: badge(text, colorClass?)
  function badge(text, colorClass) {
    return React.createElement(Badge, colorClass ? { className: colorClass } : null, text);
  }

  // Button: button(text, onClick, variant?)
  function button(text, onClick, variant) {
    var props = { onClick: onClick };
    if (variant) props.variant = variant;
    return React.createElement(Button, props, text);
  }

  // Input field: input(props)
  function input(props) {
    return React.createElement(Input, props);
  }

  // Loading spinner
  function spinner(text) {
    return React.createElement("p", null, text || "Loading...");
  }

  // ========================================================================
  // useFetch — extract the repeated fetch + setState + loading pattern
  // ========================================================================
  // Usage: const { data, loading, error, reload } = useFetch("/path", { interval: 5000 });
  function useFetch(path, options) {
    options = options || {};
    var deps = options.deps || [];
    var interval = options.interval || 0;
    var fetcher = options.fetcher || apiGet;

    var [data, setData] = useState(null);
    var [loading, setLoading] = useState(true);
    var [error, setError] = useState(null);

    var load = useCallback(async function () {
      setLoading(true);
      setError(null);
      try {
        var result = await fetcher(path);
        setData(result);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, deps.concat([path]));

    useEffect(function () { load(); }, [load]);

    // Optional polling
    useEffect(function () {
      if (!interval) return;
      var id = setInterval(load, interval);
      return function () { clearInterval(id); };
    }, [load, interval]);

    return { data: data, loading: loading, error: error, reload: load, setData: setData };
  }

  // ========================================================================
  // Main Component
  // ========================================================================

  function AgoraDashboard() {
    const [tab, setTab] = useState("projects");

    return React.createElement("div", { className: "agora-dashboard" },
      // Header
      React.createElement("div", { className: "agora-header" },
        React.createElement("h2", null, "🏛️ Agora"),
        React.createElement("p", { className: "agora-subtitle" },
          "Multi-role deliberation — manage projects, agent teams, and discussions"
        ),
      ),
      // Tabs
      React.createElement(Tabs, { value: tab, onValueChange: setTab },
        React.createElement(TabsList, null,
          React.createElement(TabsTrigger, { value: "projects" }, "Projects"),
          React.createElement(TabsTrigger, { value: "team" }, "Team"),
          React.createElement(TabsTrigger, { value: "profiles" }, "Profiles"),
        ),
      ),
      // Tab content
      tab === "projects" && React.createElement(ProjectsTab),
      tab === "team" && React.createElement(TeamTab),
      tab === "profiles" && React.createElement(ProfilesTab),
    );
  }

  // ========================================================================
  // Projects Tab — Project list + Start Project + Project Detail
  // ========================================================================

  function ProjectsTab() {
    const [projects, setProjects] = useState([]);
    const [teams, setTeams] = useState([]);
    const [leaders, setLeaders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreate, setShowCreate] = useState(false);
    const [selectedProject, setSelectedProject] = useState(null);

    const load = useCallback(async () => {
      setLoading(true);
      setError(null);
      try {
        const [p, t, l] = await Promise.all([
          apiGet("/projects").catch(() => ({ projects: [] })),
          apiGet("/teams").catch(() => ({ teams: [] })),
          apiGet("/leaders").catch(() => ({ leaders: [] })),
        ]);
        setProjects(p.projects || []);
        setTeams(t.teams || []);
        setLeaders(l.leaders || []);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    // If a project is selected, show the detail view
    if (selectedProject) {
      return React.createElement(ProjectDetail, {
        projectName: selectedProject,
        onBack: () => setSelectedProject(null),
      });
    }

    if (loading) return React.createElement("p", null, "Loading projects...");
    if (error) return React.createElement("p", { className: "agora-error" }, "Error: " + error);

    return React.createElement("div", { className: "agora-projects" },
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { onClick: () => setShowCreate(!showCreate) },
          showCreate ? "Cancel" : "+ Start Project"
        ),
        React.createElement(Button, { variant: "outline", onClick: load }, "↻ Refresh"),
      ),
      showCreate && React.createElement(StartProjectForm, {
        teams: teams,
        leaders: leaders,
        onCreated: (name) => { setShowCreate(false); setSelectedProject(name); },
      }),
      React.createElement("div", { className: "agora-project-list" },
        projects.length === 0 && React.createElement("p", { className: "agora-empty-hint" },
          "No projects yet. Click \"Start Project\" to kick off a new one."
        ),
        projects.map((p) =>
          React.createElement(ProjectCard, {
            key: p.name,
            project: p,
            onSelect: () => setSelectedProject(p.name),
            onDeleted: load,
          })
        ),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Start Project Form
  // ------------------------------------------------------------------------

  function StartProjectForm({ teams, leaders, onCreated }) {
    const [name, setName] = useState("");
    const [goal, setGoal] = useState("");
    const [workdir, setWorkdir] = useState("");
    const [team, setTeam] = useState("");
    const [leader, setLeader] = useState("");
    const [error, setError] = useState(null);
    const [creating, setCreating] = useState(false);

    const handleSubmit = async () => {
      if (!name.trim()) { setError("Project name is required"); return; }
      if (!goal.trim()) { setError("Goal is required"); return; }
      if (!workdir.trim()) { setError("Workdir path is required"); return; }
      setCreating(true);
      setError(null);
      try {
        const result = await apiPost("/projects", {
          name: name.trim(),
          goal: goal.trim(),
          workdir: workdir.trim(),
          team: team || null,
          leader: leader || null,
        });
        onCreated(result.name || name.trim());
      } catch (e) {
        setError(e.message);
      }
      setCreating(false);
    };

    return React.createElement(Card, { className: "agora-create-form" },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, "Start Project"),
      ),
      React.createElement(CardContent, null,
        error && React.createElement("p", { className: "agora-error" }, error),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Project Name"),
          React.createElement(Input, {
            value: name,
            onChange: (e) => setName(e.target.value),
            placeholder: "e.g. docmind, webapp-redesign, api-v2",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Goal"),
          React.createElement("textarea", {
            className: "agora-textarea agora-textarea-sm",
            value: goal,
            onChange: (e) => setGoal(e.target.value),
            rows: 3,
            placeholder: "What should the team accomplish? e.g. Build a doc-aware search API with React frontend",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Workdir Path"),
          React.createElement(Input, {
            value: workdir,
            onChange: (e) => setWorkdir(e.target.value),
            placeholder: "e.g. /root/docmind",
          }),
        ),
        React.createElement("div", { className: "agora-field-row" },
          React.createElement("div", { className: "agora-field" },
            React.createElement(Label, null, "Team"),
            teams.length === 0
              ? React.createElement("p", { className: "agora-hint" }, "No teams available. Create one in the Team tab.")
              : React.createElement(Select, { value: team, onValueChange: setTeam },
                  React.createElement(SelectOption, { value: "" }, "— Select Team —"),
                  teams.map((t) =>
                    React.createElement(SelectOption, { key: t.name, value: t.name }, t.name)
                  ),
                ),
          ),
          React.createElement("div", { className: "agora-field" },
            React.createElement(Label, null, "Leader (optional)"),
            leaders.length === 0
              ? React.createElement("p", { className: "agora-hint" }, "No leaders available.")
              : React.createElement(Select, { value: leader, onValueChange: setLeader },
                  React.createElement(SelectOption, { value: "" }, "— Select Leader —"),
                  leaders.map((l) =>
                    React.createElement(SelectOption, { key: l.name, value: l.name }, l.name + " (" + (l.project || "unassigned") + ")")
                  ),
                ),
          ),
        ),
        React.createElement(Button, { onClick: handleSubmit, disabled: creating },
          creating ? "Starting..." : "🚀 Start Project"
        ),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Project Card (in the list)
  // ------------------------------------------------------------------------

  function ProjectCard({ project, onSelect, onDeleted }) {
    const [deleting, setDeleting] = useState(false);

    var statusBadge;
    if (project.status === "active") {
      statusBadge = React.createElement(Badge, { className: "agora-badge-green" }, "active");
    } else if (project.status === "completed") {
      statusBadge = React.createElement(Badge, { className: "agora-badge-blue" }, "completed");
    } else if (project.status === "stopped") {
      statusBadge = React.createElement(Badge, { className: "agora-badge-red" }, "stopped");
    } else {
      statusBadge = React.createElement(Badge, null, project.status || "unknown");
    }

    var counts = project.task_counts || {};
    var total = (counts.todo || 0) + (counts.running || 0) + (counts.blocked || 0) + (counts.done || 0);

    const handleDelete = async (e) => {
      e.stopPropagation();
      if (!confirm("Stop and delete project '" + project.name + "'?")) return;
      setDeleting(true);
      try { await apiDelete("/projects/" + project.name); onDeleted(); }
      catch (e) { alert("Delete failed: " + e.message); }
      setDeleting(false);
    };

    return React.createElement(Card, {
      className: "agora-project-card",
      onClick: onSelect,
    },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-project-header" },
          React.createElement("div", { className: "agora-project-info" },
            React.createElement("span", { className: "agora-project-name" }, "📁 ", project.name),
            statusBadge,
            project.team && React.createElement(Badge, { className: "agora-badge-blue" }, "👥 " + project.team),
            project.leader && React.createElement(Badge, null, "👨‍💼 " + project.leader),
          ),
          React.createElement(Button, {
            variant: "ghost", size: "sm", onClick: handleDelete, disabled: deleting,
          }, deleting ? "..." : "Stop"),
        ),
        project.goal && React.createElement("p", { className: "agora-project-goal" }, project.goal),
        React.createElement("div", { className: "agora-project-meta" },
          React.createElement("span", null, "📋 ", total, " tasks"),
          counts.done > 0 && React.createElement("span", { className: "agora-count-done" }, "✅ ", counts.done, " done"),
          counts.running > 0 && React.createElement("span", { className: "agora-count-running" }, "🔄 ", counts.running, " running"),
          counts.todo > 0 && React.createElement("span", null, "📝 ", counts.todo, " todo"),
          counts.blocked > 0 && React.createElement("span", { className: "agora-count-blocked" }, "🚫 ", counts.blocked, " blocked"),
          project.workdir && React.createElement("span", null, "📂 ", project.workdir),
        ),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Project Detail — Overview / Kanban / Discussions / Team
  // ------------------------------------------------------------------------

  function ProjectDetail({ projectName, onBack }) {
    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [subtab, setSubtab] = useState("overview");

    const load = useCallback(async () => {
      try {
        const data = await apiGet("/projects/" + projectName);
        setProject(data);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, [projectName]);

    useEffect(() => { load(); }, [load]);

    // Auto-refresh every 10 seconds when viewing project detail
    useEffect(() => {
      var interval = setInterval(load, 10000);
      return function () { clearInterval(interval); };
    }, [load]);

    if (loading) return React.createElement("p", null, "Loading project...");
    if (error) return React.createElement("div", null,
      React.createElement(Button, { variant: "ghost", size: "sm", onClick: onBack }, "← Back to Projects"),
      React.createElement("p", { className: "agora-error" }, "Error: " + error),
    );

    var counts = project.task_counts || {};

    return React.createElement("div", { className: "agora-project-detail" },
      React.createElement("div", { className: "agora-project-detail-header" },
        React.createElement(Button, { variant: "ghost", size: "sm", onClick: onBack }, "← Back to Projects"),
        React.createElement("div", { className: "agora-project-detail-title" },
          React.createElement("h3", null, "📁 ", project.name),
          project.status === "active" && React.createElement(Badge, { className: "agora-badge-green" }, "active"),
          project.status === "completed" && React.createElement(Badge, { className: "agora-badge-blue" }, "completed"),
          project.status === "stopped" && React.createElement(Badge, { className: "agora-badge-red" }, "stopped"),
        ),
      ),
      project.goal && React.createElement("p", { className: "agora-project-goal" }, project.goal),
      React.createElement(Tabs, { value: subtab, onValueChange: setSubtab },
        React.createElement(TabsList, null,
          React.createElement(TabsTrigger, { value: "overview" }, "Overview"),
          React.createElement(TabsTrigger, { value: "kanban" }, "Kanban (" + ((counts.todo || 0) + (counts.running || 0) + (counts.blocked || 0) + (counts.done || 0)) + ")"),
          React.createElement(TabsTrigger, { value: "discussions" }, "Discussions"),
          React.createElement(TabsTrigger, { value: "team" }, "Team"),
        ),
      ),
      subtab === "overview" && React.createElement(ProjectOverview, { project: project }),
      subtab === "kanban" && React.createElement(ProjectKanban, { projectName: projectName }),
      subtab === "discussions" && React.createElement(ProjectDiscussions, { projectName: projectName }),
      subtab === "team" && React.createElement(ProjectTeam, { project: project }),
    );
  }

  // ------------------------------------------------------------------------
  // Project Overview sub-tab
  // ------------------------------------------------------------------------

  function ProjectOverview({ project }) {
    var counts = project.task_counts || {};
    var total = (counts.todo || 0) + (counts.running || 0) + (counts.blocked || 0) + (counts.done || 0);
    var progressPct = total > 0 ? Math.round(((counts.done || 0) / total) * 100) : 0;

    return React.createElement(Card, { className: "agora-project-overview" },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-overview-grid" },
          React.createElement("div", { className: "agora-stat-box" },
            React.createElement("div", { className: "agora-stat-number" }, counts.todo || 0),
            React.createElement("div", { className: "agora-stat-label" }, "📝 Todo"),
          ),
          React.createElement("div", { className: "agora-stat-box" },
            React.createElement("div", { className: "agora-stat-number agora-stat-running" }, counts.running || 0),
            React.createElement("div", { className: "agora-stat-label" }, "🔄 Running"),
          ),
          React.createElement("div", { className: "agora-stat-box" },
            React.createElement("div", { className: "agora-stat-number agora-stat-blocked" }, counts.blocked || 0),
            React.createElement("div", { className: "agora-stat-label" }, "🚫 Blocked"),
          ),
          React.createElement("div", { className: "agora-stat-box" },
            React.createElement("div", { className: "agora-stat-number agora-stat-done" }, counts.done || 0),
            React.createElement("div", { className: "agora-stat-label" }, "✅ Done"),
          ),
        ),
        React.createElement("div", { className: "agora-progress-section" },
          React.createElement("div", { className: "agora-progress-label" },
            React.createElement("span", null, "Progress"),
            React.createElement("span", null, progressPct + "%"),
          ),
          React.createElement("div", { className: "agora-progress-bar" },
            React.createElement("div", { className: "agora-progress-fill", style: { width: progressPct + "%" } }),
          ),
        ),
        React.createElement("div", { className: "agora-project-meta" },
          project.team && React.createElement("span", null, "👥 Team: ", project.team),
          project.leader && React.createElement("span", null, "👨‍💼 Leader: ", project.leader),
          project.workdir && React.createElement("span", null, "📂 ", project.workdir),
        ),
        project.created_at && React.createElement("div", { className: "agora-project-meta" },
          React.createElement("span", null, "🕒 Created ", isoTimeAgo(project.created_at)),
        ),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Project Kanban sub-tab
  // ------------------------------------------------------------------------

  function ProjectKanban({ projectName }) {
    const [tasks, setTasks] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
      try {
        const data = await fetchJSON("/api/kanban/tasks?project=" + encodeURIComponent(projectName));
        setTasks(data.tasks || []);
        setError(null);
      } catch (e) {
        // Kanban API may not exist for this project — show empty state, not error
        setTasks([]);
        setError(null);
      }
      setLoading(false);
    }, [projectName]);

    useEffect(() => { load(); }, [load]);

    // Poll every 5 seconds for task updates
    useEffect(() => {
      var interval = setInterval(load, 5000);
      return function () { clearInterval(interval); };
    }, [load]);

    if (loading) return React.createElement("p", null, "Loading kanban board...");

    // Group tasks by status
    var grouped = { todo: [], running: [], blocked: [], done: [] };
    tasks.forEach(function (t) {
      var s = t.status || "todo";
      if (!grouped[s]) grouped[s] = [];
      grouped[s].push(t);
    });

    var columns = [
      { key: "todo", title: "📝 Todo", cls: "agora-kanban-todo" },
      { key: "running", title: "🔄 Running", cls: "agora-kanban-running" },
      { key: "blocked", title: "🚫 Blocked", cls: "agora-kanban-blocked" },
      { key: "done", title: "✅ Done", cls: "agora-kanban-done" },
    ];

    if (tasks.length === 0 && !error) {
      return React.createElement("p", { className: "agora-empty-hint" },
        "No tasks found. Tasks are managed via the Hermes kanban API for this project."
      );
    }

    return React.createElement("div", { className: "agora-kanban" },
      React.createElement("div", { className: "agora-kanban-board" },
        columns.map(function (col) {
          return React.createElement("div", { key: col.key, className: cn("agora-kanban-column", col.cls) },
            React.createElement("div", { className: "agora-kanban-col-header" },
              React.createElement("span", null, col.title),
              React.createElement(Badge, null, grouped[col.key] ? grouped[col.key].length : 0),
            ),
            React.createElement("div", { className: "agora-kanban-col-body" },
              (grouped[col.key] || []).map(function (t) {
                return React.createElement("div", { key: t.id || t.title, className: "agora-kanban-task" },
                  React.createElement("div", { className: "agora-kanban-task-title" }, t.title || t.id),
                  t.description && React.createElement("p", { className: "agora-kanban-task-desc" }, t.description),
                  React.createElement("div", { className: "agora-kanban-task-meta" },
                    t.assignee && React.createElement(Badge, { className: "agora-badge-blue" }, t.assignee),
                    t.priority && React.createElement(Badge, null, t.priority),
                  ),
                );
              }),
              (!grouped[col.key] || grouped[col.key].length === 0) &&
                React.createElement("p", { className: "agora-kanban-empty" }, "—"),
            ),
          );
        }),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Project Discussions sub-tab — motions + real-time discussion + user input
  // ------------------------------------------------------------------------

  function ProjectDiscussions({ projectName }) {
    const [motions, setMotions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selectedMotion, setSelectedMotion] = useState(null);

    const load = useCallback(async () => {
      try {
        const data = await apiGet("/motions?status=all&limit=50");
        // Filter motions by project name in the source field
        var filtered = (data.motions || []).filter(function (m) {
          return m.source === projectName || (m.source && m.source.indexOf(projectName) >= 0);
        });
        setMotions(filtered);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, [projectName]);

    useEffect(() => { load(); }, [load]);

    if (loading) return React.createElement("p", null, "Loading discussions...");

    return React.createElement("div", { className: "agora-project-discussions" },
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { variant: "outline", onClick: load }, "↻ Refresh"),
        React.createElement(Button, {
          variant: "outline",
          onClick: async function () {
            var title = prompt("Discussion topic for project '" + projectName + "':");
            if (!title) return;
            try {
              await apiPost("/motions", { title: title, source: projectName, project: projectName, max_steps: 30 });
              load();
            } catch (e) { alert("Failed: " + e.message); }
          },
        }, "+ New Discussion"),
      ),
      error && React.createElement("p", { className: "agora-error" }, "Error: " + error),
      React.createElement("div", { className: "agora-discussion-layout" },
        // Motion list sidebar
        React.createElement("div", { className: "agora-discussion-sidebar" },
          React.createElement("h4", { className: "agora-sidebar-title" }, "Discussions"),
          motions.length === 0 && React.createElement("p", { className: "agora-empty-hint" },
            "No discussions yet for this project."
          ),
          motions.map(function (m) {
            return React.createElement("div", {
              key: m.motion_id,
              className: cn("agora-discussion-item", selectedMotion === m.motion_id && "selected"),
              onClick: function () { setSelectedMotion(selectedMotion === m.motion_id ? null : m.motion_id); },
            },
              React.createElement("div", { className: "agora-discussion-item-title" },
                m.status === "closed" ? "✅ " : "🔄 ",
                m.title
              ),
              React.createElement("div", { className: "agora-discussion-item-meta" },
                React.createElement("span", null, m.motion_id),
                m.decision && React.createElement(Badge, null, m.decision),
              ),
            );
          }),
        ),
        // Active discussion view
        React.createElement("div", { className: "agora-discussion-main" },
          selectedMotion
            ? React.createElement(DiscussionView, { motionId: selectedMotion })
            : React.createElement("p", { className: "agora-empty-hint" },
                "Select a discussion from the left to view the conversation."
              ),
        ),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Discussion View — real-time messages + user input for human participation
  // ------------------------------------------------------------------------

  function DiscussionView({ motionId }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);
    const [userInput, setUserInput] = useState("");
    const [sending, setSending] = useState(false);
    const messagesEndRef = useRef(null);

    const load = useCallback(async () => {
      try {
        var d = await apiGet("/motions/" + motionId);
        setData(d);
      } catch (e) {
        // silently fail on poll — keep existing data
      }
      setLoading(false);
    }, [motionId]);

    useEffect(function () {
      setLoading(true);
      load();
    }, [load]);

    // Poll every 3 seconds when viewing an active (non-closed) motion
    useEffect(function () {
      if (loading) return;
      var isActive = data && data.status !== "closed";
      if (!isActive) return;
      var interval = setInterval(load, 3000);
      return function () { clearInterval(interval); };
    }, [load, data, loading]);

    // Scroll to bottom on new messages
    useEffect(function () {
      if (messagesEndRef.current) {
        messagesEndRef.current.scrollTop = messagesEndRef.current.scrollHeight;
      }
    }, [data]);

    var handleSend = async function () {
      if (!userInput.trim()) return;
      setSending(true);
      try {
        await apiPost("/motions/" + motionId + "/messages", {
          role: "user",
          content: userInput.trim(),
        });
        setUserInput("");
        load(); // immediately refresh
      } catch (e) {
        alert("Failed to send message: " + e.message);
      }
      setSending(false);
    };

    var handleKeyPress = function (e) {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    };

    if (loading) return React.createElement("p", null, "Loading discussion...");
    if (!data) return React.createElement("p", { className: "agora-error" }, "Failed to load discussion");

    var messages = data.messages || [];
    var isActive = data.status !== "closed";

    return React.createElement("div", { className: "agora-discussion-view" },
      React.createElement("div", { className: "agora-discussion-header" },
        React.createElement("h4", null, data.title),
        React.createElement("div", { className: "agora-discussion-info" },
          React.createElement(Badge, null, data.state || data.status),
          data.decision && React.createElement(Badge, {
            className: cn(
              data.decision === "adopted" && "agora-badge-green",
              data.decision === "rejected" && "agora-badge-red",
            )
          }, data.decision),
          React.createElement("span", { className: "agora-discussion-round" },
            "Step ", data.step_count || 0, "/", data.max_steps || "?"
          ),
          data.chair && React.createElement("span", { className: "agora-discussion-round" },
            "Chair: ", data.chair
          ),
        ),
      ),
      data.rationale && React.createElement("p", { className: "agora-rationale" }, data.rationale),
      // Messages — event-driven flow: chair opening, speaker turns, guidance, votes
      React.createElement("div", { className: "agora-discussion-messages", ref: messagesEndRef },
        messages.length === 0 && React.createElement("p", { className: "agora-empty-hint" },
          "No messages yet. The chair will open the discussion shortly."
        ),
        messages.map(function (msg) {
          var isUser = msg.role === "user";
          var isChair = msg.is_chair;
          var stepType = msg.step_type || "speak";
          var stepIcon = {
            opening: "\xF0\x9F\x93\xA2",     // 📢
            speak: "\xF0\x9F\x92\xAC",        // 💬
            guidance: "\xF0\x9F\x8E\xAF",     // 🎯
            vote_call: "\xF0\x9F\x97\xB3\xEF\xB8\x8F", // 🗳️
            vote: "\xF0\x9F\x97\xB3\xEF\xB8\x8F",      // 🗳️
            summary: "\xF0\x9F\x93\x8B",      // 📋
            human_input: "\xF0\x9F\x91\xA4",  // 👤
          }[stepType] || "\xF0\x9F\x92\xAC";
          return React.createElement("div", {
            key: msg.id || (msg.role + "-" + msg.round_num + "-" + messages.indexOf(msg)),
            className: cn(
              "agora-message",
              isUser && "agora-message-user",
              isChair && "agora-message-chair",
              stepType === "vote" && "agora-message-vote",
            ),
          },
            React.createElement("div", { className: "agora-message-header" },
              React.createElement("strong", null,
                stepIcon + " ",
                isChair ? "[Chair] " + msg.role : isUser ? msg.role : msg.role
              ),
              msg.round_num > 0 && React.createElement("span", { className: "agora-message-round" }, "S" + msg.round_num),
              msg.stance && stepType === "speak" && React.createElement(Badge, null, msg.stance),
              stepType !== "speak" && React.createElement(Badge, null, stepType),
            ),
            React.createElement("div", { className: "agora-message-content" }, msg.content),
          );
        }),
      ),
      // User input box for human participation
      isActive && React.createElement("div", { className: "agora-discussion-input" },
        React.createElement("textarea", {
          className: "agora-textarea agora-textarea-sm",
          value: userInput,
          onChange: function (e) { setUserInput(e.target.value); },
          onKeyPress: handleKeyPress,
          rows: 2,
          placeholder: "Type a message to join the discussion... (Enter to send, Shift+Enter for newline)",
        }),
        React.createElement("div", { className: "agora-discussion-input-actions" },
          React.createElement(Button, { onClick: handleSend, disabled: sending || !userInput.trim() },
            sending ? "Sending..." : "💬 Send"
          ),
        ),
      ),
      !isActive && React.createElement("p", { className: "agora-hint" },
        "This discussion is closed. No further messages can be added."
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Project Team sub-tab — workers assigned to this project
  // ------------------------------------------------------------------------

  function ProjectTeam({ project }) {
    const [workers, setWorkers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
      try {
        var data = await apiGet("/workers");
        var allWorkers = data.workers || [];
        // Filter workers assigned to this project
        var projectWorkers = allWorkers.filter(function (w) {
          return w.projects && w.projects.indexOf(project.name) >= 0;
        });
        setWorkers(projectWorkers);
        setError(null);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, [project.name]);

    useEffect(() => { load(); }, [load]);

    // Poll every 10 seconds
    useEffect(() => {
      var interval = setInterval(load, 10000);
      return function () { clearInterval(interval); };
    }, [load]);

    if (loading) return React.createElement("p", null, "Loading team...");
    if (error) return React.createElement("p", { className: "agora-error" }, "Error: " + error);

    return React.createElement("div", { className: "agora-project-team" },
      project.team && React.createElement("div", { className: "agora-project-team-header" },
        React.createElement("span", { className: "agora-team-name" }, "👥 Team: ", project.team),
        project.leader && React.createElement(Badge, { className: "agora-badge-blue" }, "👨‍💼 Leader: " + project.leader),
      ),
      workers.length === 0 && React.createElement("p", { className: "agora-empty-hint" },
        "No workers assigned to this project. Assign workers via the Team tab."
      ),
      React.createElement("div", { className: "agora-worker-list" },
        workers.map(function (w) {
          return React.createElement(Card, { key: w.name, className: "agora-worker-card" },
            React.createElement(CardContent, null,
              React.createElement("div", { className: "agora-worker-header" },
                React.createElement("div", { className: "agora-worker-info" },
                  React.createElement("span", { className: "agora-worker-name" }, w.name),
                  React.createElement(Badge, null, w.role),
                  w.model && w.model !== "inherited" && React.createElement(Badge, { className: "agora-badge-blue" }, w.model),
                ),
              ),
              React.createElement("p", { className: "agora-worker-desc" }, w.description || ""),
              React.createElement("div", { className: "agora-worker-meta" },
                w.status && React.createElement("span", null, "● ", w.status),
                w.current_task && React.createElement("span", null, "📋 ", w.current_task),
                w.last_active && React.createElement("span", null, "🕒 ", isoTimeAgo(w.last_active)),
              ),
            ),
          );
        }),
      ),
    );
  }

  // ========================================================================
  // Team Tab — Workers + Leaders + Teams + Templates
  // ========================================================================

  function TeamTab() {
    const [subtab, setSubtab] = useState("workers");
    return React.createElement("div", { className: "agora-team" },
      React.createElement(Tabs, { value: subtab, onValueChange: setSubtab },
        React.createElement(TabsList, null,
          React.createElement(TabsTrigger, { value: "workers" }, "Workers"),
          React.createElement(TabsTrigger, { value: "leaders" }, "Leaders"),
          React.createElement(TabsTrigger, { value: "teams" }, "Teams"),
        ),
      ),
      subtab === "workers" && React.createElement(WorkersTab),
      subtab === "leaders" && React.createElement(LeadersTab),
      subtab === "teams" && React.createElement(TeamsTab),
    );
  }

  // ------------------------------------------------------------------------
  // Workers Sub-Tab
  // ------------------------------------------------------------------------

  function WorkersTab() {
    const [workers, setWorkers] = useState([]);
    const [templates, setTemplates] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreate, setShowCreate] = useState(false);

    const load = useCallback(async () => {
      setLoading(true);
      setError(null);
      try {
        const [w, t] = await Promise.all([
          apiGet("/workers").catch(() => ({ workers: [] })),
          apiGet("/workers/templates").catch(() => ({ templates: [] })),
        ]);
        setWorkers(w.workers || []);
        setTemplates(t.templates || []);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return React.createElement("p", null, "Loading workers...");
    if (error) return React.createElement("p", { className: "agora-error" }, "Error: " + error);

    return React.createElement("div", { className: "agora-workers" },
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { onClick: () => setShowCreate(!showCreate) },
          showCreate ? "Cancel" : "+ Create Worker"
        ),
        React.createElement(Button, { variant: "outline", onClick: load }, "↻ Refresh"),
      ),
      // Templates gallery
      !showCreate && templates.length > 0 && React.createElement("div", { className: "agora-templates-gallery" },
        React.createElement("p", { className: "agora-section-hint" },
          "Available role templates — click \"Create Worker\" to instantiate one"
        ),
        React.createElement("div", { className: "agora-template-cards" },
          templates.map((t) =>
            React.createElement(Card, {
              key: t.role,
              className: "agora-template-card",
              onClick: () => setShowCreate(true),
            },
              React.createElement(CardContent, null,
                React.createElement("div", { className: "agora-template-header" },
                  React.createElement("span", { className: "agora-template-icon" }, t.icon || "👤"),
                  React.createElement("span", { className: "agora-template-name" }, t.display_name),
                  t.is_leader && React.createElement(Badge, { className: "agora-badge-blue" }, "leader"),
                ),
                React.createElement("p", { className: "agora-template-desc" }, t.description),
              ),
            )
          ),
        ),
      ),
      // Create form
      showCreate && React.createElement(CreateWorkerForm, {
        templates: templates,
        onCreated: () => { setShowCreate(false); load(); },
      }),
      // Worker list
      !showCreate && React.createElement("div", { className: "agora-worker-list" },
        workers.length === 0 && React.createElement("p", { className: "agora-empty-hint" },
          "No workers yet. Create one from a template above."
        ),
        workers.map((w) =>
          React.createElement(WorkerCard, {
            key: w.name,
            worker: w,
            onDeleted: load,
          })
        ),
      ),
    );
  }

  function CreateWorkerForm({ templates, onCreated }) {
    const [name, setName] = useState("");
    const [role, setRole] = useState("");
    const [cloneFrom, setCloneFrom] = useState("coder");
    const [model, setModel] = useState("");
    const [error, setError] = useState(null);
    const [creating, setCreating] = useState(false);

    const selectedTemplate = templates.find((t) => t.role === role);

    const handleSubmit = async () => {
      if (!name.trim()) { setError("Name is required"); return; }
      if (!role) { setError("Select a role template"); return; }
      setCreating(true);
      setError(null);
      try {
        await apiPost("/workers", {
          name: name.trim(),
          role: role,
          clone_from: cloneFrom || "coder",
          model: model || null,
        });
        setName(""); setRole(""); setModel("");
        onCreated();
      } catch (e) {
        setError(e.message);
      }
      setCreating(false);
    };

    return React.createElement(Card, { className: "agora-create-form" },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, "Create Worker"),
      ),
      React.createElement(CardContent, null,
        error && React.createElement("p", { className: "agora-error" }, error),
        // Template selector as cards
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Role Template"),
          React.createElement("div", { className: "agora-template-picker" },
            templates.map((t) =>
              React.createElement("div", {
                key: t.role,
                className: cn("agora-template-pick", role === t.role && "selected"),
                onClick: () => setRole(t.role),
              },
                React.createElement("span", { className: "agora-template-icon" }, t.icon || "👤"),
                React.createElement("div", null,
                  React.createElement("span", { className: "agora-template-pick-name" }, t.display_name),
                  t.is_leader && React.createElement(Badge, { className: "agora-badge-blue agora-badge-sm" }, "leader"),
                ),
              )
            ),
          ),
        ),
        selectedTemplate && React.createElement("p", { className: "agora-template-preview" },
          selectedTemplate.description
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Worker Name"),
          React.createElement(Input, {
            value: name,
            onChange: (e) => setName(e.target.value),
            placeholder: "e.g. backend-dev, api-architect, qa-tester-1",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Clone Config From"),
          React.createElement(Input, {
            value: cloneFrom,
            onChange: (e) => setCloneFrom(e.target.value),
            placeholder: "coder",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Model Override (optional)"),
          React.createElement(Input, {
            value: model,
            onChange: (e) => setModel(e.target.value),
            placeholder: "inherit from parent",
          }),
        ),
        React.createElement(Button, { onClick: handleSubmit, disabled: creating },
          creating ? "Creating..." : "Create Worker"
        ),
      ),
    );
  }

  function WorkerCard({ worker, onDeleted }) {
    const [deleting, setDeleting] = useState(false);

    const handleDelete = async () => {
      if (!confirm(`Delete worker '${worker.name}'? This also deletes the Hermes profile.`)) return;
      setDeleting(true);
      try {
        await apiDelete("/workers/" + worker.name);
        onDeleted();
      } catch (e) {
        alert("Delete failed: " + e.message);
      }
      setDeleting(false);
    };

    return React.createElement(Card, { className: "agora-worker-card" },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-worker-header" },
          React.createElement("div", { className: "agora-worker-info" },
            React.createElement("span", { className: "agora-worker-name" }, worker.name),
            React.createElement(Badge, null, worker.role),
            worker.model && worker.model !== "inherited" && React.createElement(Badge, { className: "agora-badge-blue" }, worker.model),
          ),
          React.createElement(Button, {
            variant: "ghost",
            size: "sm",
            onClick: handleDelete,
            disabled: deleting,
          }, deleting ? "..." : "Delete"),
        ),
        React.createElement("p", { className: "agora-worker-desc" }, worker.description || ""),
        React.createElement("div", { className: "agora-worker-meta" },
          worker.projects && worker.projects.length > 0
            ? React.createElement("span", null, "📦 ", worker.projects.join(", "))
            : React.createElement("span", null, "📦 no projects"),
          React.createElement("span", null, "🕒 ", isoTimeAgo(worker.created_at) || "unknown"),
        ),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Leaders Sub-Tab
  // ------------------------------------------------------------------------

  function LeadersTab() {
    const [leaders, setLeaders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreate, setShowCreate] = useState(false);

    const load = useCallback(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiGet("/leaders");
        setLeaders(data.leaders || []);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return React.createElement("p", null, "Loading leaders...");
    if (error) return React.createElement("p", { className: "agora-error" }, "Error: " + error);

    return React.createElement("div", { className: "agora-leaders" },
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { onClick: () => setShowCreate(!showCreate) },
          showCreate ? "Cancel" : "+ Create Leader"
        ),
        React.createElement(Button, { variant: "outline", onClick: load }, "↻ Refresh"),
      ),
      showCreate && React.createElement(CreateLeaderForm, { onCreated: () => { setShowCreate(false); load(); } }),
      React.createElement("div", { className: "agora-leader-list" },
        leaders.length === 0 && React.createElement("p", { className: "agora-empty-hint" },
          "No leaders yet. A leader monitors a project and wakes up on a heartbeat schedule."
        ),
        leaders.map((l) =>
          React.createElement(LeaderCard, { key: l.name, leader: l, onChanged: load })
        ),
      ),
    );
  }

  function CreateLeaderForm({ onCreated }) {
    const [name, setName] = useState("");
    const [project, setProject] = useState("");
    const [heartbeat, setHeartbeat] = useState("15");
    const [cloneFrom, setCloneFrom] = useState("coder");
    const [model, setModel] = useState("");
    const [error, setError] = useState(null);
    const [creating, setCreating] = useState(false);

    const handleSubmit = async () => {
      if (!name.trim()) { setError("Name is required"); return; }
      if (!project.trim()) { setError("Project is required"); return; }
      setCreating(true);
      setError(null);
      try {
        await apiPost("/leaders", {
          name: name.trim(),
          project: project.trim(),
          heartbeat_minutes: parseInt(heartbeat) || 15,
          clone_from: cloneFrom || "coder",
          model: model || null,
        });
        setName(""); setProject(""); setHeartbeat("15"); setModel("");
        onCreated();
      } catch (e) {
        setError(e.message);
      }
      setCreating(false);
    };

    return React.createElement(Card, { className: "agora-create-form" },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, "Create Team Leader"),
      ),
      React.createElement(CardContent, null,
        error && React.createElement("p", { className: "agora-error" }, error),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Leader Name"),
          React.createElement(Input, {
            value: name,
            onChange: (e) => setName(e.target.value),
            placeholder: "e.g. lead-docmind, frank, project-manager",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Project"),
          React.createElement(Input, {
            value: project,
            onChange: (e) => setProject(e.target.value),
            placeholder: "e.g. docmind, webapp",
          }),
        ),
        React.createElement("div", { className: "agora-field-row" },
          React.createElement("div", { className: "agora-field" },
            React.createElement(Label, null, "Heartbeat (minutes)"),
            React.createElement(Input, {
              type: "number",
              value: heartbeat,
              onChange: (e) => setHeartbeat(e.target.value),
              placeholder: "15",
            }),
          ),
          React.createElement("div", { className: "agora-field" },
            React.createElement(Label, null, "Clone From"),
            React.createElement(Input, {
              value: cloneFrom,
              onChange: (e) => setCloneFrom(e.target.value),
              placeholder: "coder",
            }),
          ),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Model Override (optional)"),
          React.createElement(Input, {
            value: model,
            onChange: (e) => setModel(e.target.value),
            placeholder: "inherit from parent",
          }),
        ),
        React.createElement("p", { className: "agora-hint" },
          "A cron job will be auto-created to wake this leader every " + (heartbeat || "15") + " minutes."
        ),
        React.createElement(Button, { onClick: handleSubmit, disabled: creating },
          creating ? "Creating..." : "Create Leader"
        ),
      ),
    );
  }

  function LeaderCard({ leader, onChanged }) {
    const [busy, setBusy] = useState(false);
    const [editingHeartbeat, setEditingHeartbeat] = useState(false);
    const [newHb, setNewHb] = useState(String(leader.heartbeat_minutes || 15));

    const handleDelete = async () => {
      if (!confirm(`Delete leader '${leader.name}'? This removes the profile and cron job.`)) return;
      setBusy(true);
      try { await apiDelete("/leaders/" + leader.name); onChanged(); }
      catch (e) { alert("Delete failed: " + e.message); }
      setBusy(false);
    };

    const handleTrigger = async () => {
      setBusy(true);
      try {
        const result = await apiPost("/leaders/" + leader.name + "/heartbeat/trigger", {});
        alert("Heartbeat triggered: PID " + (result.pid || "unknown"));
      } catch (e) { alert("Trigger failed: " + e.message); }
      setBusy(false);
    };

    const handlePause = async () => {
      setBusy(true);
      try { await apiPut("/leaders/" + leader.name + "/pause", {}); onChanged(); }
      catch (e) { alert("Pause failed: " + e.message); }
      setBusy(false);
    };

    const handleResume = async () => {
      setBusy(true);
      try { await apiPut("/leaders/" + leader.name + "/resume", {}); onChanged(); }
      catch (e) { alert("Resume failed: " + e.message); }
      setBusy(false);
    };

    const handleUpdateHb = async () => {
      setBusy(true);
      try {
        await apiPut("/leaders/" + leader.name + "/heartbeat", { minutes: parseInt(newHb) });
        setEditingHeartbeat(false);
        onChanged();
      } catch (e) { alert("Update failed: " + e.message); }
      setBusy(false);
    };

    const cronEnabled = leader.cron_enabled !== false;

    return React.createElement(Card, { className: "agora-leader-card" },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-leader-header" },
          React.createElement("div", { className: "agora-leader-info" },
            React.createElement("span", { className: "agora-leader-name" }, "👨‍💼 ", leader.name),
            React.createElement(Badge, { className: "agora-badge-blue" }, leader.project || "no project"),
            cronEnabled
              ? React.createElement(Badge, { className: "agora-badge-green" }, "active")
              : React.createElement(Badge, { className: "agora-badge-red" }, "paused"),
          ),
          React.createElement(Button, {
            variant: "ghost", size: "sm", onClick: handleDelete, disabled: busy,
          }, busy ? "..." : "Delete"),
        ),
        React.createElement("div", { className: "agora-leader-meta" },
          React.createElement("span", null, "⏱️ every ", leader.heartbeat_minutes || "?", " min"),
          leader.cron_schedule && React.createElement("span", null, "📋 ", leader.cron_schedule),
          leader.last_heartbeat_at && React.createElement("span", null, "🕒 last: ", isoTimeAgo(leader.last_heartbeat_at)),
        ),
        // Heartbeat edit
        editingHeartbeat
          ? React.createElement("div", { className: "agora-hb-edit" },
              React.createElement(Input, {
                type: "number",
                value: newHb,
                onChange: (e) => setNewHb(e.target.value),
                className: "agora-hb-input",
              }),
              React.createElement(Button, { size: "sm", onClick: handleUpdateHb, disabled: busy }, "Save"),
              React.createElement(Button, { size: "sm", variant: "ghost", onClick: () => setEditingHeartbeat(false) }, "Cancel"),
            )
          : React.createElement("div", { className: "agora-leader-actions" },
              React.createElement(Button, { size: "sm", variant: "outline", onClick: () => setEditingHeartbeat(true) }, "Edit Heartbeat"),
              React.createElement(Button, { size: "sm", variant: "outline", onClick: handleTrigger, disabled: busy }, "⚡ Trigger Now"),
              cronEnabled
                ? React.createElement(Button, { size: "sm", variant: "ghost", onClick: handlePause, disabled: busy }, "⏸ Pause")
                : React.createElement(Button, { size: "sm", variant: "outline", onClick: handleResume, disabled: busy }, "▶ Resume"),
            ),
      ),
    );
  }

  // ------------------------------------------------------------------------
  // Teams Sub-Tab
  // ------------------------------------------------------------------------

  function TeamsTab() {
    const [teams, setTeams] = useState([]);
    const [workers, setWorkers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [showCreate, setShowCreate] = useState(false);

    const load = useCallback(async () => {
      setLoading(true);
      setError(null);
      try {
        const [t, w] = await Promise.all([
          apiGet("/teams").catch(() => ({ teams: [] })),
          apiGet("/workers").catch(() => ({ workers: [] })),
        ]);
        setTeams(t.teams || []);
        setWorkers(w.workers || []);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return React.createElement("p", null, "Loading teams...");
    if (error) return React.createElement("p", { className: "agora-error" }, "Error: " + error);

    return React.createElement("div", { className: "agora-teams" },
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { onClick: () => setShowCreate(!showCreate) },
          showCreate ? "Cancel" : "+ Create Team"
        ),
        React.createElement(Button, { variant: "outline", onClick: load }, "↻ Refresh"),
      ),
      showCreate && React.createElement(CreateTeamForm, {
        workers: workers,
        onCreated: () => { setShowCreate(false); load(); },
      }),
      React.createElement("div", { className: "agora-team-list" },
        teams.length === 0 && React.createElement("p", { className: "agora-empty-hint" },
          "No teams yet. Create workers first, then group them into a team for a project."
        ),
        teams.map((t) =>
          React.createElement(TeamCard, { key: t.name, team: t, onDeleted: load })
        ),
      ),
    );
  }

  function CreateTeamForm({ workers, onCreated }) {
    const [teamName, setTeamName] = useState("");
    const [project, setProject] = useState("");
    const [selected, setSelected] = useState(new Set());
    const [error, setError] = useState(null);
    const [creating, setCreating] = useState(false);

    const toggle = (name) => {
      const next = new Set(selected);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      setSelected(next);
    };

    const handleSubmit = async () => {
      if (!teamName.trim()) { setError("Team name is required"); return; }
      if (selected.size === 0) { setError("Select at least one worker"); return; }
      setCreating(true);
      setError(null);
      try {
        await apiPost("/teams", {
          team_name: teamName.trim(),
          workers: [...selected],
          project: project || null,
        });
        setTeamName(""); setProject(""); setSelected(new Set());
        onCreated();
      } catch (e) {
        setError(e.message);
      }
      setCreating(false);
    };

    return React.createElement(Card, { className: "agora-create-form" },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, "Create Team"),
      ),
      React.createElement(CardContent, null,
        error && React.createElement("p", { className: "agora-error" }, error),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Team Name"),
          React.createElement(Input, {
            value: teamName,
            onChange: (e) => setTeamName(e.target.value),
            placeholder: "e.g. docmind-team, alpha-squad",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Project (optional)"),
          React.createElement(Input, {
            value: project,
            onChange: (e) => setProject(e.target.value),
            placeholder: "e.g. docmind",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Select Workers"),
          workers.length === 0
            ? React.createElement("p", { className: "agora-hint" }, "No workers available. Create workers first.")
            : React.createElement("div", { className: "agora-worker-picker" },
                workers.map((w) =>
                  React.createElement("div", {
                    key: w.name,
                    className: cn("agora-worker-pick", selected.has(w.name) && "selected"),
                    onClick: () => toggle(w.name),
                  },
                    React.createElement(Checkbox, { checked: selected.has(w.name) }),
                    React.createElement("span", { className: "agora-worker-pick-name" }, w.name),
                    React.createElement(Badge, null, w.role),
                  )
                ),
              ),
        ),
        React.createElement(Button, { onClick: handleSubmit, disabled: creating },
          creating ? "Creating..." : "Create Team (" + selected.size + ")"
        ),
      ),
    );
  }

  function TeamCard({ team, onDeleted }) {
    const [deleting, setDeleting] = useState(false);

    const handleDelete = async () => {
      if (!confirm(`Delete team '${team.name}'?`)) return;
      setDeleting(true);
      try { await apiDelete("/teams/" + team.name); onDeleted(); }
      catch (e) { alert("Delete failed: " + e.message); }
      setDeleting(false);
    };

    return React.createElement(Card, { className: "agora-team-card" },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-team-header" },
          React.createElement("div", null,
            React.createElement("span", { className: "agora-team-name" }, "👥 ", team.name),
            team.project && React.createElement(Badge, { className: "agora-badge-blue" }, team.project),
          ),
          React.createElement(Button, {
            variant: "ghost", size: "sm", onClick: handleDelete, disabled: deleting,
          }, deleting ? "..." : "Delete"),
        ),
        React.createElement("div", { className: "agora-team-roster" },
          (team.workers || []).map((w) =>
            React.createElement("div", { key: w.name, className: "agora-team-member" },
              React.createElement("span", { className: "agora-member-name" }, w.name),
              React.createElement(Badge, null, w.role),
            )
          ),
        ),
      ),
    );
  }

  // ========================================================================
  // Profiles Tab (existing — unchanged)
  // ========================================================================

  function ProfilesTab() {
    const [profiles, setProfiles] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState(null);
    const [showCreate, setShowCreate] = useState(false);

    const load = useCallback(async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await apiGet("/profiles");
        setProfiles(data.profiles || []);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return React.createElement("p", null, "Loading profiles...");
    if (error) return React.createElement("p", { className: "agora-error" }, "Error: " + error);

    return React.createElement("div", { className: "agora-profiles" },
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { onClick: () => setShowCreate(!showCreate) },
          showCreate ? "Cancel" : "+ Create Profile"
        ),
        React.createElement(Button, {
          variant: "outline",
          onClick: async () => {
            if (!confirm("Create a full Agora team (architect + developer + reviewer)?")) return;
            try {
              const result = await apiPost("/team", { clone_from: "default" });
              alert(result.message);
              load();
            } catch (e) { alert("Failed: " + e.message); }
          },
        }, "⚡ Quick Team Setup"),
      ),
      showCreate && React.createElement(CreateProfileForm, {
        onCreated: () => { setShowCreate(false); load(); },
      }),
      React.createElement("div", { className: "agora-profile-list" },
        profiles.length === 0 && React.createElement("p", null, "No profiles yet."),
        profiles.map((p) =>
          React.createElement(ProfileCard, {
            key: p.name,
            profile: p,
            isSelected: selected === p.name,
            onSelect: () => setSelected(selected === p.name ? null : p.name),
            onDeleted: load,
          })
        ),
      ),
      selected && React.createElement(ProfileDetail, { name: selected, onChanged: load }),
    );
  }

  function CreateProfileForm({ onCreated }) {
    const [name, setName] = useState("");
    const [preset, setPreset] = useState("");
    const [cloneFrom, setCloneFrom] = useState("default");
    const [cloneConfig, setCloneConfig] = useState(true);
    const [description, setDescription] = useState("");
    const [error, setError] = useState(null);
    const [creating, setCreating] = useState(false);

    const handleSubmit = async () => {
      if (!name.trim()) { setError("Name is required"); return; }
      setCreating(true);
      setError(null);
      try {
        await apiPost("/profiles", {
          name: name.trim(),
          preset: preset || null,
          clone_from: cloneFrom || null,
          clone_config: cloneConfig,
          description: description || null,
        });
        setName(""); setPreset(""); setDescription("");
        onCreated();
      } catch (e) {
        setError(e.message);
      }
      setCreating(false);
    };

    return React.createElement(Card, { className: "agora-create-form" },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, "Create Profile"),
      ),
      React.createElement(CardContent, null,
        error && React.createElement("p", { className: "agora-error" }, error),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Profile Name"),
          React.createElement(Input, {
            value: name,
            onChange: (e) => setName(e.target.value),
            placeholder: "e.g. architect, developer, reviewer",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Preset Role"),
          React.createElement(Select, { value: preset, onValueChange: setPreset },
            React.createElement(SelectOption, { value: "" }, "— None —"),
            React.createElement(SelectOption, { value: "architect" }, "Architect"),
            React.createElement(SelectOption, { value: "developer" }, "Developer"),
            React.createElement(SelectOption, { value: "reviewer" }, "Reviewer"),
          ),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Clone From"),
          React.createElement(Input, {
            value: cloneFrom,
            onChange: (e) => setCloneFrom(e.target.value),
            placeholder: "default",
          }),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, { className: "agora-checkbox-label" },
            React.createElement(Checkbox, {
              checked: cloneConfig,
              onCheckedChange: setCloneConfig,
            }),
            " Clone config, .env, SOUL.md, skills",
          ),
        ),
        React.createElement("div", { className: "agora-field" },
          React.createElement(Label, null, "Description"),
          React.createElement(Input, {
            value: description,
            onChange: (e) => setDescription(e.target.value),
            placeholder: "What this profile is good at",
          }),
        ),
        React.createElement(Button, { onClick: handleSubmit, disabled: creating },
          creating ? "Creating..." : "Create"
        ),
      ),
    );
  }

  function ProfileCard({ profile, isSelected, onSelect, onDeleted }) {
    const [deleting, setDeleting] = useState(false);

    const handleDelete = async () => {
      if (!confirm(`Delete profile '${profile.name}'? This cannot be undone.`)) return;
      setDeleting(true);
      try {
        await apiDelete("/profiles/" + profile.name);
        onDeleted();
      } catch (e) {
        alert("Delete failed: " + e.message);
      }
      setDeleting(false);
    };

    return React.createElement(Card, {
      className: cn("agora-profile-card", isSelected && "selected"),
      onClick: onSelect,
    },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-profile-header" },
          React.createElement("div", null,
            React.createElement("span", { className: "agora-profile-name" }, profile.name),
            profile.is_default && React.createElement(Badge, { className: "agora-badge" }, "default"),
            profile.gateway_running && React.createElement(Badge, { className: "agora-badge agora-badge-green" }, "running"),
          ),
          !profile.is_default && React.createElement(Button, {
            variant: "ghost",
            size: "sm",
            onClick: (e) => { e.stopPropagation(); handleDelete(); },
            disabled: deleting,
          }, deleting ? "..." : "Delete"),
        ),
        React.createElement("div", { className: "agora-profile-meta" },
          profile.model && React.createElement("span", null, "🤖 ", profile.model),
          profile.provider && React.createElement("span", null, "🔌 ", profile.provider),
          React.createElement("span", null, "📚 ", profile.skill_count, " skills"),
        ),
        profile.description && React.createElement("p", { className: "agora-profile-desc" }, profile.description),
      ),
    );
  }

  function ProfileDetail({ name, onChanged }) {
    const [config, setConfig] = useState(null);
    const [soul, setSoul] = useState(null);
    const [skills, setSkills] = useState(null);
    const [subtab, setSubtab] = useState("config");
    const [loading, setLoading] = useState(true);

    useEffect(() => {
      setLoading(true);
      Promise.all([
        apiGet("/profiles/" + name + "/config").catch(() => null),
        apiGet("/profiles/" + name + "/soul").catch(() => null),
        apiGet("/profiles/" + name + "/skills").catch(() => null),
      ]).then(([c, s, sk]) => {
        setConfig(c); setSoul(s); setSkills(sk);
        setLoading(false);
      });
    }, [name]);

    if (loading) return React.createElement("p", null, "Loading profile detail...");

    return React.createElement(Card, { className: "agora-profile-detail" },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, "Profile: " + name),
      ),
      React.createElement(CardContent, null,
        React.createElement(Tabs, { value: subtab, onValueChange: setSubtab },
          React.createElement(TabsList, null,
            React.createElement(TabsTrigger, { value: "config" }, "Config"),
            React.createElement(TabsTrigger, { value: "soul" }, "SOUL.md"),
            React.createElement(TabsTrigger, { value: "skills" }, "Skills"),
          ),
        ),
        subtab === "config" && config && React.createElement(ConfigEditor, { name, config, onChanged }),
        subtab === "soul" && soul && React.createElement(SoulEditor, { name, soul }),
        subtab === "skills" && skills && React.createElement(SkillsList, { name, skills }),
      ),
    );
  }

  function ConfigEditor({ name, config: initialConfig, onChanged }) {
    const [model, setModel] = useState(initialConfig.model || "");
    const [provider, setProvider] = useState(initialConfig.provider || "");
    const [toolsets, setToolsets] = useState((initialConfig.toolsets || []).join(", "));
    const [disabled, setDisabled] = useState((initialConfig.disabled_toolsets || []).join(", "));
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);

    const handleSave = async () => {
      setSaving(true);
      setSaved(false);
      try {
        const toolsetList = toolsets.split(",").map(s => s.trim()).filter(Boolean);
        const disabledList = disabled.split(",").map(s => s.trim()).filter(Boolean);
        await apiPut("/profiles/" + name + "/config", {
          model: model || null,
          provider: provider || null,
          enabled_toolsets: toolsetList,
          disabled_toolsets: disabledList,
        });
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      } catch (e) {
        alert("Save failed: " + e.message);
      }
      setSaving(false);
    };

    return React.createElement("div", { className: "agora-config-editor" },
      React.createElement("div", { className: "agora-field" },
        React.createElement(Label, null, "Model"),
        React.createElement(Input, {
          value: model,
          onChange: (e) => setModel(e.target.value),
          placeholder: "e.g. deepseekv4pro, claude-sonnet-4",
        }),
      ),
      React.createElement("div", { className: "agora-field" },
        React.createElement(Label, null, "Provider"),
        React.createElement(Input, {
          value: provider,
          onChange: (e) => setProvider(e.target.value),
          placeholder: "e.g. openai, anthropic, openrouter, custom:newapi",
        }),
      ),
      React.createElement(Separator, null),
      React.createElement("div", { className: "agora-field" },
        React.createElement(Label, null, "Enabled Toolsets (comma-separated)"),
        React.createElement(Input, {
          value: toolsets,
          onChange: (e) => setToolsets(e.target.value),
          placeholder: "hermes-cli, coding, web",
        }),
      ),
      React.createElement("div", { className: "agora-field" },
        React.createElement(Label, null, "Disabled Toolsets (comma-separated)"),
        React.createElement(Input, {
          value: disabled,
          onChange: (e) => setDisabled(e.target.value),
          placeholder: "",
        }),
      ),
      React.createElement("div", { className: "agora-save-row" },
        React.createElement(Button, { onClick: handleSave, disabled: saving },
          saving ? "Saving..." : "Save Config"
        ),
        saved && React.createElement(Badge, { className: "agora-badge-green" }, "✓ Saved"),
      ),
    );
  }

  function SoulEditor({ name, soul: initial }) {
    const [content, setContent] = useState(initial.content || "");
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);

    const handleSave = async () => {
      setSaving(true);
      setSaved(false);
      try {
        await apiPut("/profiles/" + name + "/soul", { content });
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      } catch (e) {
        alert("Save failed: " + e.message);
      }
      setSaving(false);
    };

    return React.createElement("div", { className: "agora-soul-editor" },
      React.createElement("textarea", {
        className: "agora-textarea",
        value: content,
        onChange: (e) => setContent(e.target.value),
        rows: 20,
        placeholder: "Edit the SOUL.md that defines this profile's personality and role...",
      }),
      React.createElement("div", { className: "agora-save-row" },
        React.createElement(Button, { onClick: handleSave, disabled: saving },
          saving ? "Saving..." : "Save SOUL.md"
        ),
        saved && React.createElement(Badge, { className: "agora-badge-green" }, "✓ Saved"),
      ),
    );
  }

  function SkillsList({ name, skills }) {
    return React.createElement("div", { className: "agora-skills" },
      React.createElement("p", { className: "agora-skills-count" },
        skills.count + " skills available to this profile"
      ),
      React.createElement("div", { className: "agora-skills-list" },
        skills.skills.map((s) =>
          React.createElement("div", { key: s.name, className: "agora-skill-item" },
            React.createElement("span", { className: "agora-skill-name" }, s.name),
          )
        ),
      ),
    );
  }

  // ========================================================================
  // Register
  // ========================================================================

  REGISTRY.register("agora", AgoraDashboard);
})();
