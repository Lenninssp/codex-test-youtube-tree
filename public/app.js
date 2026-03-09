let trees = [];
let currentTreeId = null;

const treeList = document.getElementById('tree-list');
const emptyState = document.getElementById('empty-state');
const treeView = document.getElementById('tree-view');

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options
  });
  if (!res.ok) {
    let msg = 'Request failed';
    try {
      const data = await res.json();
      msg = data.error || msg;
    } catch (_) {}
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return res.json();
}

function renderTreeList() {
  treeList.innerHTML = '';
  trees.forEach((tree) => {
    const item = document.createElement('div');
    item.className = `tree-item ${tree.id === currentTreeId ? 'active' : ''}`;
    const statusMark = tree.status === 'archived' ? '🗄️' : '🌱';
    item.innerHTML = `
      <div>
        <strong>${statusMark} ${tree.name}</strong><br/>
        <small>${tree.status}</small>
      </div>
      <div class="tree-actions">
        <button data-act="open">Open</button>
        <button data-act="copy">Copy</button>
        <button data-act="archive">${tree.status === 'archived' ? 'Unarchive' : 'Archive'}</button>
        <button data-act="delete">Delete</button>
      </div>
    `;

    item.querySelector('[data-act="open"]').onclick = () => selectTree(tree.id);
    item.querySelector('[data-act="copy"]').onclick = async () => {
      await api(`/api/trees/${tree.id}/copy`, { method: 'POST' });
      await loadTrees();
    };
    item.querySelector('[data-act="archive"]').onclick = async () => {
      await api(`/api/trees/${tree.id}/archive`, { method: 'PATCH' });
      await loadTrees();
      if (tree.id === currentTreeId) selectTree(tree.id);
    };
    item.querySelector('[data-act="delete"]').onclick = async () => {
      await api(`/api/trees/${tree.id}`, { method: 'DELETE' });
      if (tree.id === currentTreeId) currentTreeId = null;
      await loadTrees();
      if (currentTreeId) await selectTree(currentTreeId);
      else showEmpty();
    };
    treeList.appendChild(item);
  });
}

function showEmpty() {
  treeView.classList.add('hidden');
  emptyState.classList.remove('hidden');
}

async function loadTrees() {
  const data = await api('/api/trees');
  trees = data.trees;
  renderTreeList();
}

async function selectTree(treeId) {
  currentTreeId = treeId;
  renderTreeList();
  const { tree } = await api(`/api/trees/${treeId}`);
  renderTree(tree);
}

function renderTree(tree) {
  emptyState.classList.add('hidden');
  treeView.classList.remove('hidden');

  const nodesHtml = tree.nodes.map((node) => {
    const cls = node.decision || 'pending';
    const pointsHtml = node.points?.length
      ? `<ul>${node.points.map((p) => `<li>${p.liked ? '✅' : '❌'} ${p.point_text}</li>`).join('')}</ul>`
      : '';

    const feedbackForm = !node.decision && tree.status === 'active' ? `
      <form class="feedback-form" data-node="${node.id}">
        <label>Overall decision:
          <select name="decision">
            <option value="liked">Liked</option>
            <option value="disliked">Disliked</option>
          </select>
        </label>
        <div class="points"></div>
        <button type="button" class="add-point">+ Point</button>
        <button type="submit">Submit feedback & grow next node</button>
      </form>
    ` : '';

    return `
      <article class="node ${cls}">
        <strong>Node #${node.id}</strong> <small>${node.decision || 'awaiting feedback'}</small>
        <h3>${node.title}</h3>
        <p>Channel: ${node.channel}</p>
        <p>Tags: ${node.tags.join(', ')}</p>
        <a href="https://www.youtube.com/watch?v=${node.youtube_id}" target="_blank">Watch on YouTube ↗</a>
        ${pointsHtml}
        ${feedbackForm}
      </article>
    `;
  }).join('');

  treeView.innerHTML = `<h2>${tree.name}</h2><p>Status: ${tree.status}</p>${nodesHtml}`;

  document.querySelectorAll('.feedback-form').forEach((form) => {
    const pointsEl = form.querySelector('.points');
    const addBtn = form.querySelector('.add-point');
    const nodeId = form.dataset.node;

    const addPointRow = () => {
      if (pointsEl.children.length >= 5) return;
      const row = document.createElement('div');
      row.className = 'point-row';
      row.innerHTML = `
        <input class="point-text" placeholder="Feedback point..." maxlength="120" required />
        <label><input type="checkbox" class="point-liked" checked /> positive</label>
      `;
      pointsEl.appendChild(row);
    };

    addBtn.onclick = addPointRow;
    for (let i = 0; i < 3; i++) addPointRow();

    form.onsubmit = async (e) => {
      e.preventDefault();
      const rows = [...pointsEl.querySelectorAll('.point-row')];
      if (rows.length < 3 || rows.length > 5) {
        alert('Use 3 to 5 points.');
        return;
      }
      const points = rows.map((row) => ({
        text: row.querySelector('.point-text').value,
        liked: row.querySelector('.point-liked').checked
      })).filter((p) => p.text.trim().length > 0);

      if (points.length < 3) {
        alert('Please fill at least 3 non-empty points.');
        return;
      }

      await api(`/api/nodes/${nodeId}/feedback`, {
        method: 'POST',
        body: JSON.stringify({
          decision: form.querySelector('select[name="decision"]').value,
          points
        })
      });
      await selectTree(tree.id);
      await loadTrees();
    };
  });
}

document.getElementById('new-tree-form').onsubmit = async (e) => {
  e.preventDefault();
  const name = document.getElementById('tree-name').value;
  await api('/api/trees', { method: 'POST', body: JSON.stringify({ name }) });
  document.getElementById('tree-name').value = '';
  await loadTrees();
  if (trees[0]) selectTree(trees[0].id);
};

(async function init() {
  try {
    await loadTrees();
    if (trees[0]) {
      await selectTree(trees[0].id);
    } else {
      showEmpty();
    }
  } catch (e) {
    treeView.innerHTML = `<p>Failed to load app: ${e.message}</p>`;
    treeView.classList.remove('hidden');
    emptyState.classList.add('hidden');
  }
})();
