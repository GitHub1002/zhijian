export default {
  name: 'DocTree',
  props: {
    node: { type: Object, required: true },
    query: { type: String, default: '' },
    activePath: { type: String, default: '' },
  },
  emits: ['open'],
  methods: {
    normalized() {
      return this.query.trim().toLowerCase()
    },
    fileVisible(file) {
      const query = this.normalized()
      return !query || file.name.toLowerCase().includes(query)
    },
    dirVisible(dir) {
      const query = this.normalized()
      if (!query) return true
      return (dir.files || []).some(file => this.fileVisible(file)) || (dir.dirs || []).some(child => this.dirVisible(child))
    },
    toggle(dir) {
      dir.closed = !dir.closed
    },
  },
  template: `
    <div>
      <div v-for="dir in node.dirs" v-show="dirVisible(dir)" :key="dir.name" class="tree-dir" :class="{ collapsed: dir.closed && !normalized() }">
        <div class="tree-dir-header" role="button" tabindex="0" @click="toggle(dir)" @keydown.enter.prevent="toggle(dir)" @keydown.space.prevent="toggle(dir)">
          <span class="tree-toggle">{{ dir.closed && !normalized() ? '▸' : '▾' }}</span>
          <span class="tree-dir-name">{{ dir.name }}</span>
        </div>
        <div v-show="!dir.closed || normalized()" class="tree-dir-children">
          <doc-tree :node="dir" :query="query" :active-path="activePath" @open="$emit('open', $event)"></doc-tree>
        </div>
      </div>
      <button v-for="file in node.files" v-show="fileVisible(file)" :key="file.path" type="button" class="doc-item" :class="{ active: file.path === activePath }" :title="file.path" @click="$emit('open', file.path)">{{ file.name }}</button>
    </div>
  `,
}
