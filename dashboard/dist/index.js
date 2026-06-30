// Agora Dashboard — Profile Management + Discussion Viewer
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
    const [tab, setTab] = useState("profiles");

    return React.createElement("div", { className: "agora-dashboard" },
      // Header
      React.createElement("div", { className: "agora-header" },
        React.createElement("h2", null, "🏛️ Agora"),
        React.createElement("p", { className: "agora-subtitle" },
          "Multi-role deliberation — manage agent profiles and discussions"
        ),
      ),
      // Tabs
      React.createElement(Tabs, { value: tab, onValueChange: setTab },
        React.createElement(TabsList, null,
          React.createElement(TabsTrigger, { value: "profiles" }, "Profiles"),
          React.createElement(TabsTrigger, { value: "motions" }, "Discussions"),
        ),
      ),
      // Tab content
      tab === "profiles" && React.createElement(ProfilesTab),
      tab === "motions" && React.createElement(MotionsTab),
    );
  }

  // ========================================================================
  // Profiles Tab
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
      // Create button
      React.createElement("div", { className: "agora-actions" },
        React.createElement(Button, { onClick: () => setShowCreate(!showCreate) },
          showCreate ? "Cancel" : "+ Create Profile"
        ),
      ),
      // Create form
      showCreate && React.createElement(CreateProfileForm, {
        onCreated: () => { setShowCreate(false); load(); },
      }),
      // Profile list
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
      // Selected profile detail
      selected && React.createElement(ProfileDetail, { name: selected, onChanged: load }),
    );
  }

  // ========================================================================
  // Create Profile Form
  // ========================================================================

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
          React.createElement(Select, {
            value: preset,
            onValueChange: setPreset,
          },
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

  // ========================================================================
  // Profile Card
  // ========================================================================

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

  // ========================================================================
  // Profile Detail (config + SOUL + skills)
  // ========================================================================

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

  // ========================================================================
  // Config Editor
  // ========================================================================

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

  // ========================================================================
  // SOUL Editor
  // ========================================================================

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

  // ========================================================================
  // Skills List
  // ========================================================================

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
  // Motions Tab
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
