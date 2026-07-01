// Agora Dashboard — Team Management + Profiles + Discussions
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
  // Main Component
  // ========================================================================

  function AgoraDashboard() {
    const [tab, setTab] = useState("team");

    return React.createElement("div", { className: "agora-dashboard" },
      // Header
      React.createElement("div", { className: "agora-header" },
        React.createElement("h2", null, "🏛️ Agora"),
        React.createElement("p", { className: "agora-subtitle" },
          "Multi-role deliberation — manage agent profiles, teams, and discussions"
        ),
      ),
      // Tabs
      React.createElement(Tabs, { value: tab, onValueChange: setTab },
        React.createElement(TabsList, null,
          React.createElement(TabsTrigger, { value: "team" }, "Team"),
          React.createElement(TabsTrigger, { value: "profiles" }, "Profiles"),
          React.createElement(TabsTrigger, { value: "motions" }, "Discussions"),
        ),
      ),
      // Tab content
      tab === "team" && React.createElement(TeamTab),
      tab === "profiles" && React.createElement(ProfilesTab),
      tab === "motions" && React.createElement(MotionsTab),
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
  // Motions Tab (existing — unchanged)
  // ========================================================================

  function MotionsTab() {
    const [motions, setMotions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState(null);

    const load = useCallback(async () => {
      setLoading(true);
      try {
        const data = await apiGet("/motions?status=all&limit=50");
        setMotions(data.motions || []);
      } catch (e) {
        setError(e.message);
      }
      setLoading(false);
    }, []);

    useEffect(() => { load(); }, [load]);

    if (loading) return React.createElement("p", null, "Loading discussions...");
    if (error) return React.createElement("p", { className: "agora-error" }, "Error: " + error);

    return React.createElement("div", { className: "agora-motions" },
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { onClick: load }, "↻ Refresh"),
        React.createElement(Button, {
          variant: "outline",
          onClick: async () => {
            const title = prompt("Discussion topic:");
            if (!title) return;
            try {
              const result = await apiPost("/motions", { title: title, rounds: 3 });
              alert("Motion created: " + result.motion_id + "\nUse /agora discuss in chat to start the LLM discussion.");
              load();
            } catch (e) { alert("Failed: " + e.message); }
          },
        }, "+ New Discussion"),
      ),
      React.createElement("div", { className: "agora-motion-list" },
        motions.length === 0 && React.createElement("p", null, "No discussions yet. Use /agora discuss to start one."),
        motions.map((m) =>
          React.createElement(MotionCard, {
            key: m.motion_id,
            motion: m,
            isSelected: selected === m.motion_id,
            onSelect: () => setSelected(selected === m.motion_id ? null : m.motion_id),
          })
        ),
      ),
      selected && React.createElement(MotionDetail, { motionId: selected }),
    );
  }

  function MotionCard({ motion, isSelected, onSelect }) {
    const statusIcon = motion.status === "closed" ? "✅" : "🔄";
    const decisionBadge = motion.decision
      ? React.createElement(Badge, {
          className: cn(
            "agora-badge",
            motion.decision === "adopted" && "agora-badge-green",
            motion.decision === "rejected" && "agora-badge-red",
          )
        }, motion.decision)
      : null;

    return React.createElement(Card, {
      className: cn("agora-motion-card", isSelected && "selected"),
      onClick: onSelect,
    },
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-motion-header" },
          React.createElement("span", null, statusIcon, " ", motion.title),
          decisionBadge,
        ),
        React.createElement("div", { className: "agora-motion-meta" },
          React.createElement("span", null, motion.motion_id),
          motion.source && motion.source !== "user" && React.createElement(Badge, null, motion.source),
        ),
      ),
    );
  }

  function MotionDetail({ motionId }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
      setLoading(true);
      apiGet("/motions/" + motionId).then(setData).catch(() => setData(null)).finally(() => setLoading(false));
    }, [motionId]);

    if (loading) return React.createElement("p", null, "Loading motion...");
    if (!data) return React.createElement("p", { className: "agora-error" }, "Failed to load motion");

    return React.createElement(Card, { className: "agora-motion-detail" },
      React.createElement(CardHeader, null,
        React.createElement(CardTitle, null, data.title),
      ),
      React.createElement(CardContent, null,
        React.createElement("div", { className: "agora-motion-info" },
          React.createElement(Badge, null, data.status),
          data.decision && React.createElement(Badge, null, data.decision),
          React.createElement("span", null, "Round ", data.current_round, "/", data.max_rounds),
        ),
        data.rationale && React.createElement("p", { className: "agora-rationale" }, data.rationale),
        data.action_items && data.action_items.length > 0 && React.createElement("div", { className: "agora-action-items" },
          React.createElement("h4", null, "Action Items"),
          data.action_items.map((ai, i) =>
            React.createElement("div", { key: i, className: "agora-action-item" }, "• ", ai)
          ),
        ),
        data.messages && data.messages.length > 0 && React.createElement("div", { className: "agora-messages" },
          React.createElement("h4", null, "Discussion"),
          data.messages.map((msg) =>
            React.createElement("div", { key: msg.id, className: "agora-message" },
              React.createElement("div", { className: "agora-message-header" },
                React.createElement("strong", null, msg.role),
                React.createElement("span", { className: "agora-message-round" }, "R" + msg.round),
                React.createElement(Badge, null, msg.stance),
              ),
              React.createElement("div", { className: "agora-message-content" }, msg.content),
            )
          ),
        ),
      ),
    );
  }

  // ========================================================================
  // Register
  // ========================================================================

  REGISTRY.register("agora", AgoraDashboard);
})();
