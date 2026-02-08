# Usage

## Commenting in OBS

Action `sub-comment` can be used to add comments to release requests inside OBS (like [qa-maintenance/openQABot](https://gitlab.suse.de/qa-maintenance/openQABot) did).

An example of such comment:

```
<!-- openqa state=failed revision_15-SP3_x86_64=1636983205
revision_15-SP3_ppc64le=1636982976 revision_15-SP3_s390x=1636982978
revision_15-SP3_aarch64=1636982975 revision_15.3_x86_64=0 -->


 __Group [Maintenance: Containers 15-SP3 Updates@Server-DVD-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=369&flavor=Server-DVD-Updates&distri=sle&build=20211115-1)__
 (6 tests passed)


 __Group [Maintenance: JeOS 15-SP3 Updates@JeOS-for-kvm-and-xen-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=375&flavor=JeOS-for-kvm-and-xen-Updates&distri=sle&build=20211115-1)__
 (30 tests passed)


 __Group [Maintenance: Public Cloud 15-SP3 Updates@GCE-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=370&flavor=GCE-Updates&distri=sle&build=20211115-1)__
 (5 tests passed, 1 tests failed)

 - [sle-15-SP3-GCE-Updates-x86_64-Build20211115-1-publiccloud_containers@64bit](https://openqa.suse.de/tests/7676191) failed'

 __Group [Maintenance: SLE 15 SP3 Incidents@Desktop-DVD-Incidents](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=367&flavor=Desktop-DVD-Incidents&distri=sle&build=%3A21811%3Aautoyast2)__
 (3 tests passed, 2 tests failed)

 - [sle-15-SP3-Desktop-DVD-Incidents-x86_64-Build:21811:autoyast2-qam-regression-piglit@64bit](https://openqa.suse.de/tests/7679142) is waiting'
 - [sle-15-SP3-Desktop-DVD-Incidents-x86_64-Build:21811:autoyast2-qam-regression-other@64bit](https://openqa.suse.de/tests/7679143) is waiting'


 __Group [Maintenance: SLE 15 SP3 Updates@Server-DVD-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=366&flavor=Server-DVD-Updates&distri=sle&build=20211115-1)__
 (147 tests passed)
```
