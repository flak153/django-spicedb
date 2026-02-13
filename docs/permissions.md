# Permission Expressions

Permission expressions are the logic that SpiceDB uses to decide whether a subject can perform an action on an object. They compose relations and other permissions using operators to create rewrite rules.

## Operators

### Union: `+` or `|`
Creates an OR relationship. A subject matches if it has **any one** of the specified relations or permissions.

```
view = owner + viewer
```
Means: A user can view if they are the owner OR they are in the viewer relation.

Both `+` and `|` are equivalent and interchangeable.

### Intersection: `&`
Creates an AND relationship. A subject must match **all** specified relations and permissions.

```
edit = owner & verified
```
Means: A user can edit only if they are the owner AND they have been verified.

### Exclusion: `!`
Negates a relation or permission. A subject matches if they do **not** have the specified relation.

```
public_view = anyone & !banned
```
Means: Anyone can view except those who are banned.

### Grouping: `()`
Controls evaluation order. Without grouping, operators follow standard precedence. Use parentheses to override.

```
access = (owner + viewer) & active
```
Means: Access is granted if (owner OR viewer) AND the account is active.

### Traversal: `->`
Follows a relation to another object and checks a permission on that target object. This enables permission inheritance.

```
view = owner + parent->view
```
Means: A user can view if they are the owner OR if they have view permission on the parent object.

The `->` operator is fundamental to hierarchical permission systems; it allows permissions to flow up or down trees.

## Examples

### Simple Direct Permission
```
view = owner
```
Only the owner can view. Anyone who is the object's owner has view permission.

### Union of Relations
```
view = owner + viewer
```
The owner OR anyone in the viewer relation can view.

### Traversal with Union
```
view = owner + parent->view
```
The owner can view. Also, anyone who can view the parent object can view this object. This is the pattern for hierarchical permissions: if you can view a folder, you can view everything inside it.

### Inheritance with Multiple Levels
```
manage = manager + parent->manage
```
A manager can manage the object. Also, anyone who can manage the parent can manage this object. Permissions propagate recursively up the tree.

### Combining Relations and Traversal
```
view = owner + viewer + parent->view
```
The owner can view. Anyone in the viewer relation can view. Anyone who can view the parent can view this object.

### Intersection Example
```
edit = owner & verified
```
Only the owner can edit, and the owner must also have verified status. Both conditions must be true.

### Complex Expression
```
access = (owner + team->member) & active
```
Access is granted if (owner OR a team member) AND the account is active.

## How It Maps to SpiceDB

Permission expressions compile into SpiceDB's rewrite rules. When you define:

```python
permissions = {
    'view': 'owner + parent->view'
}
```

django-spicedb converts this to SpiceDB's schema DSL:

```
definition document {
    relation owner: user
    relation parent: folder
    permission view = owner + parent->view
}
```

When you call `spicedb.check(document:1, view, user:2)`, SpiceDB evaluates the expression by:
1. Checking if there is a tuple `document:1#owner@user:2`
2. If not, checking if there is a tuple `document:1#parent@folder:X` for some folder X, then recursively checking if `folder:X#view@user:2` is true

SpiceDB handles the recursion and caching; you just write the expression.

## Syntax Rules

- **Token delimiters**: `|`, `&`, `(`, `)`, `!`, `+` are recognized as operators
- **Identifiers**: Relation and permission names are alphanumeric plus underscores
- **Whitespace**: Spaces are ignored
- **Arrow syntax**: `->` is always followed by a relation or permission name with no space required; `parent->view` is valid, `parent -> view` is also valid

## Common Patterns

### Public Access (with Restrictions)
```
read = anyone | role->read
```
Anyone can read, OR anyone who has read on a role object.

### Hierarchical Access
```
permission_name = owner + parent->permission_name
```
This pattern is self-referential: the permission of the same name on the parent flows down. It's used for folders and hierarchical resources.

### Role-Based with Fallback
```
manage = owner + team->manager
```
The owner can always manage. Also, anyone who is a manager on the linked team can manage.

### Restricted Access
```
view = verified_member & !suspended
```
Only verified members can view, and they must not be suspended.
