from django.conf.urls import patterns, url
from django.core.urlresolvers import reverse
from django.core.exceptions import PermissionDenied
from django.contrib.staticfiles import finders
from django.utils.functional import cached_property

from widgy import registry
from widgy.views import (
    NodeView,
    ContentView,
    ShelfView,
    NodeEditView,
    NodeTemplatesView,
    NodeParentsView,
    CommitView,
    HistoryView,
    ReviewedHistoryView,
    ApproveView,
    UnapproveView,
    RevertView,
    DiffView,
    ResetView,
    UndoApprovalsView,
)
from widgy.exceptions import (
    MutualRejection,
    ParentWasRejected,
    ChildWasRejected,
)


class WidgySite(object):
    def get_registry(self):
        return registry

    def get_all_content_classes(self):
        return self.get_registry().keys()

    def get_urls(self):
        urlpatterns = patterns('',
            url('^node/$', self.node_view),
            url('^node/(?P<node_pk>[^/]+)/$', self.node_view),
            url('^node/(?P<node_pk>[^/]+)/available-children-recursive/$', self.shelf_view),
            url('^node/(?P<node_pk>[^/]+)/edit/$', self.node_edit_view),
            url('^node/(?P<node_pk>[^/]+)/templates/$', self.node_templates_view),
            url('^node/(?P<node_pk>[^/]+)/possible-parents/$', self.node_parents_view),
            url('^contents/(?P<app_label>[A-z_][\w_]*)/(?P<object_name>[A-z_][\w_]*)/(?P<object_pk>[^/]+)/$', self.content_view),

            # versioning
            url('^revert/(?P<pk>[^/]+)/(?P<commit_pk>[^/]+)/$', self.revert_view),
            url('^commit/(?P<pk>[^/]+)/$', self.commit_view),
            url('^history/(?P<pk>[^/]+)/$', self.history_view),
            url('^reset/(?P<pk>[^/]+)/$', self.reset_view),
            url('^diff/(?P<before_pk>[^/]+)/(?P<after_pk>[^/]+)/$', self.diff_view),
        )
        return urlpatterns

    @property
    def urls(self):
        return self.get_urls()

    def reverse(self, *args, **kwargs):
        """
        We tried to use namespaced URLs per site just like ModelAdmins,
        however, as we refer to the views by their function objects, we can't
        use namespaces because there is a bug in Django:

        https://code.djangoproject.com/ticket/17914

        We should use named URLs instead of function references, but we
        couldn't get that working.
        """
        return reverse(*args, **kwargs)

    def authorize(self, request, view, obj=None):
        if not request.user.is_authenticated():
            raise PermissionDenied

    # These must return the same instance throughout the whole lifetime
    # of the widgy site for reverse to work.
    @cached_property
    def node_view(self):
        return NodeView.as_view(site=self)

    @cached_property
    def content_view(self):
        return ContentView.as_view(site=self)

    @cached_property
    def shelf_view(self):
        return ShelfView.as_view(site=self)

    @cached_property
    def node_edit_view(self):
        return NodeEditView.as_view(site=self)

    @cached_property
    def node_templates_view(self):
        return NodeTemplatesView.as_view(site=self)

    @cached_property
    def node_parents_view(self):
        return NodeParentsView.as_view(site=self)

    @cached_property
    def commit_view(self):
        return CommitView.as_view(site=self)

    @cached_property
    def history_view(self):
        return HistoryView.as_view(site=self)

    @cached_property
    def revert_view(self):
        return RevertView.as_view(site=self)

    @cached_property
    def diff_view(self):
        return DiffView.as_view(site=self)

    @cached_property
    def reset_view(self):
        return ResetView.as_view(site=self)

    def valid_parent_of(self, parent, child_class, child=None):
        return parent.valid_parent_of(child_class, child)

    def valid_child_of(self, parent, child_class, child=None):
        return child_class.valid_child_of(parent, child)

    def validate_relationship(self, parent, child):
        if isinstance(child, type):
            child_class = child
            child = None
        else:
            child_class = type(child)

        bad_child = not self.valid_parent_of(parent, child_class, child)
        bad_parent = not self.valid_child_of(parent, child_class, child)

        if bad_parent and bad_child:
            raise MutualRejection
        elif bad_parent:
            raise ParentWasRejected
        elif bad_child:
            raise ChildWasRejected

    def get_version_tracker_model(self):
        from widgy.models import VersionTracker
        return VersionTracker

    def filter_existing_staticfiles(self, filename):
        path = finders.find(filename)
        return bool(path)

    def find_media_files(self, extension, hierarchy=['widgy/{app_label}/{module_name}{extension}']):
        files = set()
        for widget in self.get_all_content_classes():
            files.update(widget.get_templates_hierarchy(
                hierarchy=hierarchy,
                extension=extension,
            ))
        return filter(self.filter_existing_staticfiles, files)

    @cached_property
    def scss_files(self):
        return self.find_media_files('.scss')

    @cached_property
    def js_files(self):
        return self.find_media_files('.js')

    @cached_property
    def admin_scss_files(self):
        return self.find_media_files(
            extension='.scss',
            hierarchy=[
                'widgy/{app_label}/{module_name}.admin{extension}',
                'widgy/{app_label}/admin{extension}',
            ])

    def get_commit_form(self, user):
        from widgy.views.versioning import CommitForm
        return CommitForm


class ReviewedWidgySite(WidgySite):

    def get_version_tracker_model(self):
        from widgy.models import ReviewedVersionTracker
        return ReviewedVersionTracker

    def get_urls(self):
        return super(ReviewedWidgySite, self).get_urls() + patterns('',
            url('^approve/(?P<pk>[^/]+)/(?P<commit_pk>[^/]+)/$', self.approve_view),
            url('^unapprove/(?P<pk>[^/]+)/(?P<commit_pk>[^/]+)/$', self.unapprove_view),
            url('^undo-approvals/$', self.undo_approvals_view),
        )

    def get_commit_form(self, user):
        from widgy.views.versioning import CommitForm, ReviewedCommitForm
        if user.has_perm('widgy.change_versioncommit'):
            return ReviewedCommitForm
        else:
            return CommitForm

    def authorize(self, request, view, obj=None):
        super(ReviewedWidgySite, self).authorize(request, view, obj)

        from widgy.admin import VersionCommitAdmin

        approval_views = (VersionCommitAdmin, ApproveView, UndoApprovalsView,
                          UnapproveView)
        if isinstance(view, approval_views):
            if not request.user.has_perm('widgy.change_versioncommit'):
                raise PermissionDenied

    @cached_property
    def approve_view(self):
        return ApproveView.as_view(site=self)

    @cached_property
    def unapprove_view(self):
        return UnapproveView.as_view(site=self)

    @cached_property
    def undo_approvals_view(self):
        return UndoApprovalsView.as_view(site=self)

    @cached_property
    def history_view(self):
        return ReviewedHistoryView.as_view(site=self)
