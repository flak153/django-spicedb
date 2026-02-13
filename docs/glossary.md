# ReBAC Glossary

## Tuple
A fact stored in SpiceDB representing a relationship between an object and a subject. Written in the form `object:id#relation@subject:id`, for example `document:1#owner@user:2` means "user 2 is the owner of document 1". Tuples are the atomic units of the permission graph; django-spicedb automatically writes tuples to SpiceDB when your Django models change.

## Type
A category of objects in your permission system, mapped to a Django model. Examples include `user`, `document`, `folder`, or `team`. Types define the schema for what relations and permissions exist; every object in SpiceDB belongs to exactly one type.

## Relation
A named edge between an object and a subject, representing a direct relationship. Examples include `owner` (the object's owner), `viewer` (someone who can view the object), or `member` (someone who is a member of a group). Relations are declared in your type's configuration and automatically synced when Django fields change.

## Subject
The entity that has a relationship to an object, typically represented as `type:id`. For example, in the tuple `document:1#owner@user:2`, the subject is `user:2`. Subjects are what SpiceDB checks permissions for.

## Object
The entity that a relationship is on, represented as `type:id`. For example, in the tuple `document:1#owner@user:2`, the object is `document:1`. Permissions are always evaluated with respect to an object.

## Permission
A computed check composed of relations using logical expressions that SpiceDB evaluates. Permissions are not stored as tuples; instead, they are rewrite rules that compose relations to answer questions like "can user:2 view document:1?" Examples include `view = owner + parent->view` (owner can view, OR anyone who can view the parent) or `edit = owner & verified` (must be both owner AND verified).

## Binding
A mapping from a Django model field to a ReBAC relation, telling the library how to automatically sync tuples when your models change. A binding declares the field name and kind (fk for foreign key, m2m for many-to-many, through for through-tables, or manual for custom logic). When you save or delete a Django object, django-spicedb uses bindings to decide which tuples to write or delete in SpiceDB.

## Through Binding
A binding for a many-to-many relationship that uses a through-table with a role field, mapping different role values to different relations. For example, a TeamMembership through-table with a role field (`member` or `manager`) allows django-spicedb to write different tuples based on the role: `team:1#member@user:2` if the role is "member", or `team:1#manager@user:2` if the role is "manager". This enables fine-grained role-based access control without manual signal handlers.

## TypeGraph
The internal registry that validates all type configurations and compiles them to SpiceDB schema. When django-spicedb starts up, it reads your type definitions from settings, validates that parents exist, that relations point to known types, that permissions reference only known relations, and that bindings target defined relations. The TypeGraph then compiles the whole graph into SpiceDB's schema language (definition blocks with relations and permissions).
